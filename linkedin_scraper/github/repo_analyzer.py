"""File selection + repo tree/content fetch + monorepo detection for the
LLM repo-insight layer. Selects a small, budget-capped, priority-ordered
subset of files from a repository rather than sending the whole repo tree
to the LLM.
"""

import base64
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .client import GitHubClient
from .hygiene import _CI_NAMES, _DOCKER_NAMES, _MANIFEST_NAMES, _TEST_DIR_NAMES
from ..core.exceptions import NetworkError, RateLimitError

logger = logging.getLogger(__name__)

MAX_FILES_PER_REPO = 25
MAX_FILE_BYTES = 100_000
MIN_FILES_PER_SUBPROJECT = 5
REST_CONCURRENCY = 5

_ENTRYPOINT_NAMES = {
    "main.py", "app.py", "index.js", "index.ts", "server.js", "server.ts",
    "main.go", "main.rs", "main.java",
}
_MANIFEST_NAMES_EXT = _MANIFEST_NAMES | {"requirements.txt"}
_SKIP_DIR_PREFIXES = ("node_modules/", "vendor/", "dist/", "build/", ".git/")
_SKIP_FILE_EXTENSIONS = (
    ".min.js", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".pdf", ".zip", ".lock",
)
_SOURCE_FILE_EXTENSIONS = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".php",
    ".c", ".cpp", ".h", ".hpp", ".cs", ".swift", ".kt", ".scala",
)
_DOCSTRING_RE = re.compile(r'("""|\'\'\'|/\*\*|\bdef \w+\([^)]*\):\s*\n\s*["\'])')


@dataclass
class TreeEntry:
    path: str
    size_bytes: int


@dataclass
class RepoTreeResult:
    entries: List[TreeEntry] = field(default_factory=list)
    truncated: bool = False
    root_sha: Optional[str] = None


@dataclass
class SelectedFile:
    path: str
    size_bytes: int
    category: str  # manifest|readme|ci|docker|entrypoint|test|sample


async def fetch_repo_tree(client: GitHubClient, owner: str, repo: str, branch: str) -> RepoTreeResult:
    """GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1"""
    try:
        status, data, _ = await client.rest_get(
            f"/repos/{owner}/{repo}/git/trees/{branch}", params={"recursive": "1"}
        )
    except (NetworkError, RateLimitError) as e:
        logger.debug(f"tree fetch failed for {owner}/{repo}: {e}")
        return RepoTreeResult()

    if status != 200 or not data:
        return RepoTreeResult()

    entries = [
        TreeEntry(path=node["path"], size_bytes=node.get("size", 0) or 0)
        for node in data.get("tree", [])
        if node.get("type") == "blob"
    ]
    return RepoTreeResult(entries=entries, truncated=bool(data.get("truncated", False)), root_sha=data.get("sha"))


def detect_monorepo(tree: RepoTreeResult) -> Tuple[bool, List[str]]:
    """Manifests found at 2+ distinct directory depths/subpaths -> monorepo guess.
    A heuristic, explicitly named as a guess by the caller (is_monorepo_guess)."""
    manifest_dirs = set()
    for entry in tree.entries:
        name = entry.path.rsplit("/", 1)[-1].lower()
        if name in _MANIFEST_NAMES_EXT:
            directory = entry.path.rsplit("/", 1)[0] if "/" in entry.path else ""
            manifest_dirs.add(directory)

    if len(manifest_dirs) >= 2:
        return True, sorted(d for d in manifest_dirs if d)
    return False, []


def _is_test_path(path: str) -> bool:
    base = path.rsplit("/", 1)[-1].lower()
    return (
        any(part.lower() in _TEST_DIR_NAMES for part in path.split("/"))
        or any(base.endswith(suf) for suf in ("_test.py", ".test.js", "_spec.rb"))
    )


def compute_test_to_source_file_ratio(tree: RepoTreeResult) -> Optional[float]:
    """Ratio of test files to source files across the full repo tree - a
    deterministic anchor for the LLM's testing_presence band, not a
    replacement for it."""
    candidates = [e for e in tree.entries if not _is_skippable(e.path, e.size_bytes)]
    if not candidates:
        return None

    source_files = [
        e for e in candidates
        if e.path.lower().endswith(_SOURCE_FILE_EXTENSIONS) and not _is_test_path(e.path)
    ]
    test_files = [e for e in candidates if _is_test_path(e.path)]
    if not source_files:
        return None
    return len(test_files) / len(source_files)


def compute_docstring_density(contents: Dict[str, str]) -> Optional[float]:
    """Fraction of sampled source files (by content already fetched for the
    LLM prompt) containing a docstring/doc-comment pattern - a deterministic
    anchor for the LLM's documentation_quality band."""
    source_contents = {
        path: text for path, text in contents.items()
        if path.lower().endswith(_SOURCE_FILE_EXTENSIONS) and not _is_test_path(path)
    }
    if not source_contents:
        return None
    with_docstrings = sum(1 for text in source_contents.values() if _DOCSTRING_RE.search(text))
    return with_docstrings / len(source_contents)


def _is_skippable(path: str, size_bytes: int) -> bool:
    if any(path.startswith(prefix) for prefix in _SKIP_DIR_PREFIXES):
        return True
    if any(path.lower().endswith(ext) for ext in _SKIP_FILE_EXTENSIONS):
        return True
    if size_bytes > MAX_FILE_BYTES:
        return True
    return False


def select_files_for_analysis(
    tree: RepoTreeResult,
    max_files: int = MAX_FILES_PER_REPO,
    max_file_bytes: int = MAX_FILE_BYTES,
) -> List[SelectedFile]:
    """Priority order: manifests, README, CI config, Dockerfile, entrypoints,
    a small test sample, then a representative source sample. Monorepo-aware:
    allocates budget proportionally across detected subprojects."""
    candidates = [e for e in tree.entries if not _is_skippable(e.path, e.size_bytes)]
    is_monorepo, subproject_dirs = detect_monorepo(tree)

    def base_name(path: str) -> str:
        return path.rsplit("/", 1)[-1]

    manifests = [e for e in candidates if base_name(e.path).lower() in _MANIFEST_NAMES_EXT]
    readmes = [e for e in candidates if base_name(e.path).lower().startswith("readme")]
    ci_files = [
        e for e in candidates
        if e.path.split("/")[0] in _CI_NAMES or base_name(e.path).lower() in _CI_NAMES
    ]
    docker_files = [e for e in candidates if base_name(e.path).lower() in _DOCKER_NAMES]
    entrypoints = [e for e in candidates if base_name(e.path).lower() in _ENTRYPOINT_NAMES]
    tests = sorted(
        (
            e for e in candidates
            if any(part.lower() in _TEST_DIR_NAMES for part in e.path.split("/"))
            or any(base_name(e.path).lower().endswith(suf) for suf in ("_test.py", ".test.js", "_spec.rb"))
        ),
        key=lambda e: e.size_bytes,
    )[:3]

    selected: List[SelectedFile] = []
    already_selected_paths = set()

    def add(entries: List[TreeEntry], category: str) -> None:
        for e in entries:
            if len(selected) >= max_files or e.path in already_selected_paths:
                continue
            selected.append(SelectedFile(path=e.path, size_bytes=e.size_bytes, category=category))
            already_selected_paths.add(e.path)

    add(manifests, "manifest")
    add(readmes, "readme")
    add(ci_files, "ci")
    add(docker_files, "docker")
    add(entrypoints, "entrypoint")
    add(tests, "test")

    remaining_budget = max_files - len(selected)
    if remaining_budget > 0:
        remaining_candidates = [e for e in candidates if e.path not in already_selected_paths]
        sample = _select_representative_sample(
            remaining_candidates, remaining_budget, subproject_dirs if is_monorepo else None
        )
        add(sample, "sample")

    return selected


def _select_representative_sample(
    entries: List[TreeEntry], budget: int, subproject_dirs: Optional[List[str]]
) -> List[TreeEntry]:
    if not entries:
        return []

    sizes = sorted(e.size_bytes for e in entries)
    median_size = sizes[len(sizes) // 2]

    def dir_prefix(path: str) -> str:
        return path.rsplit("/", 1)[0] if "/" in path else ""

    if subproject_dirs:
        per_group_budget = max(MIN_FILES_PER_SUBPROJECT, budget // max(1, len(subproject_dirs)))
        result: List[TreeEntry] = []
        for group_dir in subproject_dirs:
            group_entries = sorted(
                (e for e in entries if e.path.startswith(group_dir)),
                key=lambda e: abs(e.size_bytes - median_size),
            )
            result.extend(group_entries[:per_group_budget])
            if len(result) >= budget:
                break
        return result[:budget]

    seen_dirs: set = set()
    breadth_first: List[TreeEntry] = []
    for e in sorted(entries, key=lambda e: abs(e.size_bytes - median_size)):
        d = dir_prefix(e.path)
        if d not in seen_dirs:
            breadth_first.append(e)
            seen_dirs.add(d)
        if len(breadth_first) >= budget:
            break

    if len(breadth_first) < budget:
        remaining = [e for e in entries if e not in breadth_first]
        remaining_sorted = sorted(remaining, key=lambda e: abs(e.size_bytes - median_size))
        breadth_first.extend(remaining_sorted[: budget - len(breadth_first)])

    return breadth_first[:budget]


async def fetch_file_contents(
    client: GitHubClient, owner: str, repo: str, files: List[SelectedFile]
) -> Dict[str, str]:
    """GET /repos/{owner}/{repo}/contents/{path} per selected file, base64-decoded,
    concurrency-capped. Fault-tolerant per file: a failed fetch is simply omitted."""
    import asyncio

    semaphore = asyncio.Semaphore(REST_CONCURRENCY)
    results: Dict[str, str] = {}

    async def fetch_one(file: SelectedFile) -> None:
        async with semaphore:
            try:
                status, data, _ = await client.rest_get(f"/repos/{owner}/{repo}/contents/{file.path}")
                if status == 200 and data and data.get("content"):
                    decoded = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                    results[file.path] = decoded
            except (NetworkError, RateLimitError) as e:
                logger.debug(f"content fetch failed for {owner}/{repo}/{file.path}: {e}")

    await asyncio.gather(*(fetch_one(f) for f in files))
    return results

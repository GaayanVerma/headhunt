"""Framework/library detection from manifest file contents.

Deliberately narrow: parses only package.json, requirements.txt,
pyproject.toml, go.mod, and Gemfile (the manifest types most repos on
GitHub actually use), and filters detected dependency names against a
small curated allowlist of recognizable frameworks/libraries so
transitive/obscure dependencies don't get surfaced as "skills". Every
parser is fault-tolerant - malformed manifest content yields an empty
list rather than raising, since this runs as a best-effort enrichment
over arbitrary user-authored repos.
"""

import json
import re
from typing import Callable, Dict, List

_VERSION_STRIP_RE = re.compile(r"^[A-Za-z0-9_.\-]+")
_GEMFILE_GEM_RE = re.compile(r"""^\s*gem\s+['"]([^'"]+)['"]""", re.MULTILINE)
_GO_REQUIRE_LINE_RE = re.compile(r"^\s*([^\s]+)\s+v[\d\w.\-+]+", re.MULTILINE)

_FRAMEWORK_ALLOWLIST = {
    "react", "react-dom", "next", "vue", "angular", "svelte", "express",
    "fastify", "nestjs", "@nestjs/core", "django", "flask", "fastapi",
    "rails", "sinatra", "spring", "spring-boot", "pytest", "jest", "mocha",
    "pandas", "numpy", "scipy", "tensorflow", "torch", "pytorch",
    "scikit-learn", "sqlalchemy", "gin-gonic/gin", "echo", "celery",
    "redis", "graphql", "apollo-server", "tailwindcss", "bootstrap",
}


def _parse_package_json(content: str) -> List[str]:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    names: List[str] = []
    for key in ("dependencies", "devDependencies"):
        deps = data.get(key)
        if isinstance(deps, dict):
            names.extend(deps.keys())
    return names


def _parse_requirements_txt(content: str) -> List[str]:
    names: List[str] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        match = _VERSION_STRIP_RE.match(line)
        if match:
            names.append(match.group(0))
    return names


def _parse_pyproject_toml(content: str) -> List[str]:
    names: List[str] = []
    in_deps_block = False
    for line in content.splitlines():
        stripped = line.strip()
        if re.match(r"^\[(tool\.poetry\.(dependencies|dev-dependencies)|project)\]", stripped):
            in_deps_block = re.match(r"^\[tool\.poetry\.(dependencies|dev-dependencies)\]", stripped) is not None
            continue
        if stripped.startswith("["):
            in_deps_block = False
            continue
        if in_deps_block and "=" in stripped:
            key = stripped.split("=", 1)[0].strip().strip('"')
            if key and key.lower() != "python":
                names.append(key)
        elif stripped.startswith("dependencies") and "=" in stripped:
            # PEP 621 `dependencies = ["foo>=1.0", ...]` on project.dependencies
            list_part = stripped.split("=", 1)[1]
            for item in re.findall(r'"([^"]+)"', list_part):
                match = _VERSION_STRIP_RE.match(item)
                if match:
                    names.append(match.group(0))
    return names


def _parse_go_mod(content: str) -> List[str]:
    names: List[str] = []
    for match in _GO_REQUIRE_LINE_RE.finditer(content):
        path = match.group(1)
        names.append(path.rstrip("/").split("/")[-1])
        names.append(path.rstrip("/"))
    return names


def _parse_gemfile(content: str) -> List[str]:
    return _GEMFILE_GEM_RE.findall(content)


_DEPENDENCY_PARSERS: Dict[str, Callable[[str], List[str]]] = {
    "package.json": _parse_package_json,
    "requirements.txt": _parse_requirements_txt,
    "pyproject.toml": _parse_pyproject_toml,
    "go.mod": _parse_go_mod,
    "gemfile": _parse_gemfile,
}


def extract_repo_frameworks(manifest_contents: Dict[str, str]) -> List[str]:
    """manifest_contents: {filename (as found in repo root): file content}.
    Returns deduped, allowlist-filtered framework/library names."""
    found: List[str] = []
    for filename, content in manifest_contents.items():
        parser = _DEPENDENCY_PARSERS.get(filename.lower())
        if parser is None:
            continue
        try:
            found.extend(parser(content))
        except Exception:
            continue

    seen = set()
    frameworks: List[str] = []
    for name in found:
        key = name.lower()
        if key in _FRAMEWORK_ALLOWLIST and key not in seen:
            seen.add(key)
            frameworks.append(name)
    return frameworks

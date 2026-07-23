"""Pure heuristics for repo engineering-hygiene flags, given a root file/dir listing."""

import re
from typing import Iterable, List

_CI_NAMES = {".github", ".circleci", ".travis.yml"}
_TEST_DIR_NAMES = {"test", "tests", "__tests__", "spec"}
_DOCKER_NAMES = {"dockerfile", "docker-compose.yml", "docker-compose.yaml", ".devcontainer"}
_LINT_NAME_RE = re.compile(
    r"^(\.eslintrc.*|\.flake8|ruff\.toml|\.golangci\.ya?ml|\.pylintrc|\.prettierrc.*)$",
    re.IGNORECASE,
)
_MANIFEST_NAMES = {
    "package.json", "pyproject.toml", "setup.py", "requirements.txt", "go.mod",
    "cargo.toml", "pom.xml", "build.gradle", "gemfile", "composer.json",
}
_TUTORIAL_PATTERN = re.compile(
    r"tutorial|course|bootcamp|udemy|freecodecamp|leetcode|hw\d|assignment|coursework|100days",
    re.IGNORECASE,
)


def has_ci(file_names: Iterable[str]) -> bool:
    lower = {n.lower() for n in file_names}
    return bool(lower & _CI_NAMES)


def has_tests(file_names: Iterable[str]) -> bool:
    lower = {n.lower() for n in file_names}
    if lower & _TEST_DIR_NAMES:
        return True
    return any(re.search(r"(_test\.\w+$|\.test\.\w+$|_spec\.\w+$)", n, re.IGNORECASE) for n in file_names)


def has_docker(file_names: Iterable[str]) -> bool:
    lower = {n.lower() for n in file_names}
    return bool(lower & _DOCKER_NAMES)


def has_lint_config(file_names: Iterable[str]) -> bool:
    if any(_LINT_NAME_RE.match(n) for n in file_names):
        return True
    return "pyproject.toml" in {n.lower() for n in file_names}  # may hold [tool.ruff]/[tool.black]; caller can refine


def has_package_manifest(file_names: Iterable[str]) -> bool:
    lower = {n.lower() for n in file_names}
    return bool(lower & _MANIFEST_NAMES)


def guess_repo_type(name: str, description: str, is_fork: bool, is_template: bool) -> str:
    """Heuristic label - never treated as verified fact by downstream consumers."""
    if is_fork:
        return "FORK"
    if is_template:
        return "TEMPLATE_INSTANCE"
    haystack = f"{name} {description or ''}"
    if _TUTORIAL_PATTERN.search(haystack):
        return "TUTORIAL_FOLLOW_ALONG"
    return "ORIGINAL"


def guess_is_portfolio_demo(homepage_url: str, topics: List[str], name: str) -> bool:
    if not homepage_url:
        return False
    topic_text = " ".join(topics).lower()
    if any(t in topic_text for t in ("portfolio", "demo", "showcase")):
        return True
    return bool(re.search(r"portfolio|showcase|demo", name, re.IGNORECASE))

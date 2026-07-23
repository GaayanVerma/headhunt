"""Resolve a GitHub username out of whatever URL/handle form the resume parser found."""

import re
from typing import Optional
from urllib.parse import urlparse

# Paths that are GitHub product/marketing pages, never a user/org profile.
_RESERVED_PATHS = {
    "orgs", "organizations", "marketplace", "sponsors", "settings", "notifications",
    "issues", "pulls", "explore", "topics", "trending", "collections", "events",
    "features", "about", "pricing", "security", "contact", "site", "apps", "login",
    "join", "dashboard", "codespaces", "gist", "search", "watching", "stars",
}

_USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")


def resolve_github_username(raw_url_or_handle: str) -> Optional[str]:
    """Extract a candidate GitHub username from a URL or bare handle.

    Handles missing scheme, www prefix, trailing slash, query/fragment.
    Returns None if the input doesn't resolve to a plausible profile path
    (e.g. it's a reserved GitHub path, or a repo/deep-link URL).
    """
    if not raw_url_or_handle:
        return None

    candidate = raw_url_or_handle.strip()
    if "github.com" not in candidate and not candidate.startswith(("http://", "https://")):
        # Bare handle case, e.g. "janedoe" or "@janedoe"
        candidate = candidate.lstrip("@")
        if _USERNAME_RE.match(candidate) and candidate.lower() not in _RESERVED_PATHS:
            return candidate
        return None

    if not candidate.startswith(("http://", "https://")):
        candidate = "https://" + candidate

    parsed = urlparse(candidate)
    if "github.com" not in parsed.netloc.lower():
        return None

    path_parts = [p for p in parsed.path.split("/") if p]
    if not path_parts:
        return None

    username = path_parts[0]
    if username.lower() in _RESERVED_PATHS:
        return None
    if not _USERNAME_RE.match(username):
        return None

    # More than one path segment means this is a repo/deep link, not a
    # profile root (e.g. github.com/janedoe/some-repo). Still return the
    # owner as a strong hint - callers may treat single-segment vs
    # multi-segment differently if they need the distinction.
    return username

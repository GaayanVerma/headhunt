"""Content-hash based caches to avoid re-fetching unchanged repo trees/files
and re-generating LLM insights for content that hasn't changed since a prior
run. Both caches are opt-in and fail open: a cache read/write error is a
cache miss, never a hard pipeline failure."""

import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def content_hash(*parts: str) -> str:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part.encode("utf-8", errors="replace"))
        hasher.update(b"\x00")
    return hasher.hexdigest()


class DiskCache:
    """Simple on-disk JSON cache, one file per key, under a per-candidate
    `.github_cache/` directory. Fails open on any I/O error."""

    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir

    def _path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.json")

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            path = self._path(key)
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"cache read miss/error for key {key}: {e}")
            return None

    def set(self, key: str, value: Dict[str, Any]) -> None:
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(self._path(key), "w", encoding="utf-8") as f:
                json.dump(value, f)
        except Exception as e:
            logger.debug(f"cache write failed for key {key}: {e}")


def repo_snapshot_cache_key(owner: str, repo: str, commit_sha: str) -> str:
    return f"tree_{owner}_{repo}_{commit_sha}"


def llm_insight_cache_key(selected_file_contents: str, prompt_version: str, model: str) -> str:
    return f"llm_insight_{content_hash(selected_file_contents, prompt_version, model)}"

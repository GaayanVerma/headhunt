"""Parse authority-agent text into AuthorityReview without importing CrewAI."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional

from .models import AuthorityReview


def parse_authority_review(raw: Any) -> AuthorityReview:
    """Best-effort parse of the authority agent's final output into AuthorityReview."""
    if isinstance(raw, AuthorityReview):
        return raw
    text = raw if isinstance(raw, str) else getattr(raw, "raw", None) or str(raw)
    payload = _extract_json_object(text)
    if payload is None:
        return AuthorityReview(summary=text[:2000] if text else "No structured review returned.")
    return AuthorityReview.model_validate(payload)


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None

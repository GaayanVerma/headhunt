"""Deterministic career-timeline construction: merges Person.experiences and
Person.educations into one chronologically-sorted CareerTimeline, with
kind/transition tags derived from rules over LinkedIn's own data - no LLM
call anywhere in this module (replaces journey_tagger.py's Anthropic-backed
promotion/transition/function/pivot classification).
"""

import re
from datetime import datetime
from typing import List, Optional, Tuple

from ..models.person import Education, Experience, Person
from ..models.timeline import CareerTimeline, TimelineEntry, TimelineEntryKind

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

_EMPLOYMENT_TYPE_MAP = {
    "full-time": "full_time",
    "part-time": "part_time",
    "contract": "contract",
    "freelance": "freelance",
    "internship": "internship",
    "seasonal": "seasonal",
    "self-employed": "self_employed",
    "apprenticeship": "apprenticeship",
}

_SENTINEL_UNKNOWN_START = (9999, 12)


def _parse_month_year(text: Optional[str]) -> Optional[Tuple[int, int]]:
    """Parse a LinkedIn date fragment like "Jan 2020" or "2020" into a
    sortable (year, month) tuple. Returns None if no year is found."""
    if not text:
        return None
    stripped = text.strip()
    if not stripped or stripped.lower() == "present":
        return None
    year_match = _YEAR_RE.search(stripped)
    if not year_match:
        return None
    year = int(year_match.group())
    month = 1
    lowered = stripped.lower()
    for name, num in _MONTHS.items():
        if name in lowered:
            month = num
            break
    return (year, month)


def _sort_key(from_date: Optional[str], to_date: Optional[str]) -> Tuple[int, int]:
    parsed = _parse_month_year(from_date)
    if parsed is not None:
        return parsed
    parsed = _parse_month_year(to_date)
    if parsed is not None:
        return parsed
    return _SENTINEL_UNKNOWN_START


def _entry_kind_for_experience(experience: Experience) -> TimelineEntryKind:
    if not experience.employment_type:
        return "unknown"
    return _EMPLOYMENT_TYPE_MAP.get(experience.employment_type.strip().lower(), "unknown")


def _compute_total_years_experience(experiences: List[Experience]) -> Optional[float]:
    start_years: List[int] = []
    end_years: List[int] = []
    for e in experiences:
        start = _parse_month_year(e.from_date)
        if start is not None:
            start_years.append(start[0])
        end = _parse_month_year(e.to_date)
        end_years.append(end[0] if end is not None else datetime.now().year)

    if not start_years:
        return None
    span = max(end_years) - min(start_years)
    return float(span) if span >= 0 else None


def build_career_timeline(person: Person) -> CareerTimeline:
    """Merge person.experiences + person.educations into one chronological,
    deterministically-tagged CareerTimeline. Never calls an LLM."""
    work_items = [
        (_sort_key(e.from_date, e.to_date), "work", e) for e in person.experiences
    ]
    education_items = [
        (_sort_key(e.from_date, e.to_date), "education", e) for e in person.educations
    ]
    merged = sorted(work_items + education_items, key=lambda item: item[0])

    entries: List[TimelineEntry] = []
    previous_work: Optional[Experience] = None

    for _sort_key_value, item_type, item in merged:
        if item_type == "education":
            edu: Education = item
            entries.append(
                TimelineEntry(
                    kind="education",
                    transition=None,
                    title=edu.degree,
                    institution=edu.institution_name,
                    from_date=edu.from_date,
                    to_date=edu.to_date,
                    duration=None,
                    description=edu.description,
                    domain_changed=False,
                )
            )
            continue

        experience: Experience = item
        if previous_work is None:
            transition = "first_role"
            domain_changed = False
        elif experience.institution_name != previous_work.institution_name:
            transition = "transition"
            domain_changed = True
        elif experience.position_title != previous_work.position_title:
            transition = "promotion"
            domain_changed = False
        else:
            transition = "function_change"
            domain_changed = False

        entries.append(
            TimelineEntry(
                kind=_entry_kind_for_experience(experience),
                transition=transition,
                title=experience.position_title,
                institution=experience.institution_name,
                from_date=experience.from_date,
                to_date=experience.to_date,
                duration=experience.duration,
                description=experience.description,
                domain_changed=domain_changed,
            )
        )
        previous_work = experience

    return CareerTimeline(
        entries=entries,
        total_years_experience=_compute_total_years_experience(person.experiences),
    )

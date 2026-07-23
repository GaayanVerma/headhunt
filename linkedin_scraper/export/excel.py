"""Excel export for candidate search results."""

from pathlib import Path
from typing import List, Union

from ..models.person_search import PersonSearchResult


def export_candidates_to_excel(
    candidates: List[PersonSearchResult],
    output_path: Union[str, Path],
) -> Path:
    """
    Export candidates to an Excel file.

    Requires openpyxl: pip install openpyxl
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError as exc:
        raise ImportError(
            "openpyxl is required for Excel export. Install with: pip install openpyxl"
        ) from exc

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Candidates"

    headers = [
        "Rank",
        "Name",
        "LinkedIn URL",
        "Headline",
        "Location",
        "Fit Score",
        "Fit Indicators",
        "Connection",
        "Mutual Connections",
        "Followers",
        "Premium",
        "Verified",
        "Source Query",
    ]
    sheet.append(headers)

    header_font = Font(bold=True)
    for cell in sheet[1]:
        cell.font = header_font

    for index, candidate in enumerate(candidates, start=1):
        sheet.append(
            [
                index,
                candidate.name,
                candidate.linkedin_url,
                candidate.headline or "",
                candidate.location or "",
                candidate.fit_score,
                candidate.fit_indicators_text,
                candidate.connection_degree or "",
                candidate.mutual_connections or "",
                candidate.followers or "",
                "Yes" if candidate.is_premium else "",
                "Yes" if candidate.is_verified else "",
                candidate.search_query or "",
            ]
        )

    sheet.auto_filter.ref = sheet.dimensions
    sheet.freeze_panes = "A2"

    for column in sheet.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            value = str(cell.value) if cell.value is not None else ""
            max_length = max(max_length, min(len(value), 60))
        sheet.column_dimensions[column_letter].width = max(12, max_length + 2)

    workbook.save(path)
    return path

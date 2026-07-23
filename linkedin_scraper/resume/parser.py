"""PDF resume parser — extracts links, email, phone, skills, and projects from a resume PDF."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import pypdf
except ImportError as e:
    raise ImportError("pypdf is required for resume parsing: pip install pypdf") from e

from ..models.resume import ResumeData, ResumeProject

_URL_RE = re.compile(r'https?://[^\s<>"\')\]]+')
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(
    r'(?:\+?1[\s.\-]?)?'
    r'(?:\(?\d{3}\)?[\s.\-]?)'
    r'\d{3}[\s.\-]?\d{4}'
)

_STRIP_CHARS = '.,;:)]\'"/>'

_SKILLS_HEADERS = {
    "skills", "technical skills", "core skills", "skills & tools",
    "skills and tools", "technologies", "tech stack", "areas of expertise",
}
_PROJECTS_HEADERS = {
    "projects", "personal projects", "academic projects", "key projects",
    "selected projects", "side projects",
}
_ALL_SECTION_HEADERS = _SKILLS_HEADERS | _PROJECTS_HEADERS | {
    "experience", "work experience", "employment", "education",
    "summary", "objective", "certifications", "publications", "awards",
    "interests", "languages", "volunteer", "volunteering", "contact",
}

_BULLET_RE = re.compile(r'^[\s•\-\*•●‣⁃]+')
_TECH_LABEL_RE = re.compile(r'^(tech(?:nologies)?|stack|tools)\s*:\s*(.+)$', re.IGNORECASE)
_BRACKETED_RE = re.compile(r'[\(\[]([^\)\]]+)[\)\]]')


def _clean_url(url: str) -> str:
    return url.rstrip(_STRIP_CHARS)


def _clean_url(url: str) -> str:
    return url.rstrip(_STRIP_CHARS)


def _extract_annotation_urls(reader: "pypdf.PdfReader") -> List[str]:
    urls: List[str] = []
    for page in reader.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        for annot in annots:
            obj = annot.get_object() if hasattr(annot, "get_object") else annot
            action = obj.get("/A")
            if action:
                uri = action.get("/URI")
                if uri and not str(uri).startswith("mailto:"):
                    urls.append(str(uri))
    return urls


def _categorize(urls: List[str]) -> Tuple[Optional[str], Optional[str], List[str]]:
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    other: List[str] = []
    for url in urls:
        lower = url.lower()
        if "linkedin.com" in lower:
            if linkedin_url is None:
                linkedin_url = url
        elif "github.com" in lower:
            if github_url is None:
                github_url = url
        else:
            other.append(url)
    return linkedin_url, github_url, other


_HEADER_PATTERNS: List[Tuple[str, "re.Pattern"]] = sorted(
    (
        (
            header,
            re.compile(
                r"^\s*" + r"\s+".join(re.escape(w) for w in header.split()) + r"\b\s*:?\s*(.*)$",
                re.IGNORECASE,
            ),
        )
        for header in _ALL_SECTION_HEADERS
    ),
    key=lambda pair: -len(pair[0]),
)


def _split_sections(raw_text: str) -> Dict[str, str]:
    """Slice raw resume text into {lowercased header: body} for recognized
    section headers. A line counts as a header if it *starts* with a known
    header phrase (case-insensitive, tolerant of PDF-extraction whitespace
    quirks between words) - this also covers the common case where PDF text
    extraction glues a header onto the start of its first content line
    (e.g. "Projects   ● Klang.ai ..."), so we don't misfire on prose
    that happens to mention "skills" mid-sentence but also don't lose a
    section whose header shares a line with its first bullet."""
    lines = raw_text.splitlines()
    header_hits: List[Tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        for header, pattern in _HEADER_PATTERNS:
            match = pattern.match(line)
            if match:
                header_hits.append((i, header, match.group(1).strip()))
                break

    sections: Dict[str, str] = {}
    for idx, (line_no, header, remainder) in enumerate(header_hits):
        end = header_hits[idx + 1][0] if idx + 1 < len(header_hits) else len(lines)
        rest = "\n".join(lines[line_no + 1:end]).strip()
        body = f"{remainder}\n{rest}".strip() if remainder else rest
        if body:
            sections[header] = body
    return sections


def _parse_skills_section(body: str) -> List[str]:
    raw_items: List[str] = []
    for line in body.splitlines():
        line = _BULLET_RE.sub("", line).strip()
        if not line:
            continue
        for chunk in re.split(r'[,•|]', line):
            chunk = chunk.strip().strip(".")
            if chunk:
                raw_items.append(chunk)

    seen = set()
    skills: List[str] = []
    for item in raw_items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            skills.append(item)
    return skills


def _looks_like_title(line: str) -> bool:
    """A title line is short, not a bullet/URL, doesn't read as prose (no
    trailing '.'), and isn't a "Tech:"/"Stack:"/"Tools:" label line."""
    line = line.strip()
    if not line or len(line) > 80:
        return False
    if _BULLET_RE.match(line) or line.startswith(("http", "www.")):
        return False
    if _TECH_LABEL_RE.match(line):
        return False
    if line.endswith("."):
        return False
    return True


_UNICODE_BULLET_SPLIT_RE = re.compile(r'[•●‣⁃]\s*')
_TECH_LABEL_INLINE_RE = re.compile(r'\b(tech(?:nologies)?|stack|tools)\s*:\s*(.+)$', re.IGNORECASE)
_NAME_DASH_RE = re.compile(r'^([^\-:]{1,80}?)\s*[\-:]\s*(.+)$')


def _parse_projects_section(body: str) -> List[ResumeProject]:
    """Some PDF text extractors emit one word per line for justified
    paragraphs, which makes a per-line title heuristic useless. Bulleted
    project lists (the common case) are far more reliably split on the
    bullet glyph itself after collapsing the body to a single line; the
    per-line title heuristic is only used as a fallback for bullet-free
    input (e.g. one project per blank-line-separated block)."""
    normalized = re.sub(r'\s+', ' ', body).strip()
    if not normalized:
        return []

    items = [chunk.strip() for chunk in _UNICODE_BULLET_SPLIT_RE.split(normalized) if chunk.strip()]
    if len(items) > 1:
        projects: List[ResumeProject] = []
        for item in items:
            technologies: List[str] = []
            description = item
            tech_match = _TECH_LABEL_INLINE_RE.search(item)
            if tech_match:
                technologies = [t.strip() for t in tech_match.group(2).split(",") if t.strip()]
                description = (item[:tech_match.start()] + item[tech_match.end():]).strip()

            name = None
            name_match = _NAME_DASH_RE.match(description)
            if name_match:
                name = name_match.group(1).strip()
                description = name_match.group(2).strip()

            projects.append(
                ResumeProject(name=name, description=description or None, technologies=technologies)
            )
        return projects

    return _parse_projects_by_title_lines(body)


def _parse_projects_by_title_lines(body: str) -> List[ResumeProject]:
    lines = [ln for ln in body.splitlines() if ln.strip()]
    if not lines:
        return []

    title_indices = [i for i, ln in enumerate(lines) if _looks_like_title(ln)]
    if not title_indices:
        return [ResumeProject(description=body.strip())]

    projects: List[ResumeProject] = []
    for idx, start in enumerate(title_indices):
        end = title_indices[idx + 1] if idx + 1 < len(title_indices) else len(lines)
        name = lines[start].strip()
        body_lines = lines[start + 1:end]

        technologies: List[str] = []
        description_lines: List[str] = []
        for ln in body_lines:
            stripped = _BULLET_RE.sub("", ln).strip()
            tech_match = _TECH_LABEL_RE.match(stripped)
            if tech_match:
                technologies.extend(
                    t.strip() for t in tech_match.group(2).split(",") if t.strip()
                )
            else:
                description_lines.append(stripped)

        bracket_match = _BRACKETED_RE.search(name)
        if bracket_match:
            technologies.extend(t.strip() for t in bracket_match.group(1).split(",") if t.strip())
            name = _BRACKETED_RE.sub("", name).strip()

        projects.append(
            ResumeProject(
                name=name or None,
                description="\n".join(description_lines).strip() or None,
                technologies=technologies,
            )
        )
    return projects


class ResumeParser:
    """Parse a PDF resume and extract structured link/contact data."""

    def parse(self, pdf_path: str) -> ResumeData:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"Resume not found: {pdf_path}")

        reader = pypdf.PdfReader(str(path))

        pages_text = []
        for page in reader.pages:
            text = page.extract_text() or ""
            pages_text.append(text)
        raw_text = "\n".join(pages_text)

        annotation_urls = _extract_annotation_urls(reader)
        text_urls = [
            _clean_url(u) for u in _URL_RE.findall(raw_text)
            if not u.startswith("mailto:")
        ]

        seen = set()
        all_urls: List[str] = []
        for url in annotation_urls + text_urls:
            url = _clean_url(url)
            if url and url not in seen:
                seen.add(url)
                all_urls.append(url)

        linkedin_url, github_url, other_urls = _categorize(all_urls)

        email_match = _EMAIL_RE.search(raw_text)
        email = email_match.group(0) if email_match else None

        phone_match = _PHONE_RE.search(raw_text)
        phone = phone_match.group(0).strip() if phone_match else None

        sections = _split_sections(raw_text)
        skills: List[str] = []
        for header in _SKILLS_HEADERS:
            if header in sections:
                skills.extend(_parse_skills_section(sections[header]))
        seen_skills = set()
        skills = [s for s in skills if not (s.lower() in seen_skills or seen_skills.add(s.lower()))]

        projects: List[ResumeProject] = []
        for header in _PROJECTS_HEADERS:
            if header in sections:
                projects.extend(_parse_projects_section(sections[header]))

        return ResumeData(
            raw_text=raw_text,
            links=all_urls,
            linkedin_url=linkedin_url,
            github_url=github_url,
            other_urls=other_urls,
            email=email,
            phone=phone,
            skills=skills,
            projects=projects,
        )

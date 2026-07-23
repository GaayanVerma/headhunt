#!/usr/bin/env python3
"""One-off: run the Startup Readiness Evaluation stage against an already-captured
scrape_output.log (avoids re-running the GitHub/LinkedIn scrape pipeline).

Usage:
    python scripts/run_readiness_from_log.py candidates/Achintya/scrape_output.log
"""
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from linkedin_scraper.evaluation import ReadinessEvaluator
from linkedin_scraper.github.candidate_summary import build_candidate_github_summary
from linkedin_scraper.models.github import (
    AggregateFeatures,
    GitHubAnalysisResult,
    GitHubProfile,
    Limitations,
    LLMSnapshot,
    ParserMetadata,
    SourceMetadata,
)
from linkedin_scraper.models.person import Person
from linkedin_scraper.models.resume import ResumeData

sys.path.pop(0)


def parse_log(log_path: Path):
    text = log_path.read_text()

    def field(pattern, cast=str, default=None):
        m = re.search(pattern, text)
        if not m:
            return default
        return cast(m.group(1))

    # --- resume ---
    resume = ResumeData(
        email=field(r"Email:\s+(\S+)"),
        phone=field(r"Phone:\s+(\S+)"),
        linkedin_url=field(r"LinkedIn:\s+(\S+)"),
        github_url=field(r"GitHub:\s+(\S+)"),
    )

    # --- github_facts (deterministic aggregate features + profile) ---
    login = field(r"Login:\s+(\S+)") or log_path.parent.name
    profile = GitHubProfile(
        login=login,
        name=field(r"Name:\s+(.+)"),
        bio=field(r"Bio:\s+(.+)"),
        followers_count=field(r"Followers:\s+(\d+)", int, 0),
        public_repos_count=field(r"Public repos:\s+(\d+)", int, 0),
    )
    aggregate_features = AggregateFeatures(
        original_repos_count=field(r"Original repos:\s+(\d+)", int, 0),
        forked_repos_count=field(r"forks excluded:\s+(\d+)", int, 0),
        active_repos_90d=field(r"Active in 90d:\s+(\d+)", int, 0),
        total_stars=field(r"Total stars:\s+(\d+)", int, 0),
        documentation_coverage_ratio=field(r"Documentation cov:\s+([\d.]+)", float, 0.0),
        testing_coverage_ratio=field(r"Testing coverage:\s+([\d.]+)", float, 0.0),
        ci_coverage_ratio=field(r"CI coverage:\s+([\d.]+)", float, 0.0),
    )
    github_facts = GitHubAnalysisResult(
        source_metadata=SourceMetadata(
            input_url_raw=field(r"Input URL:\s+(\S+)") or f"https://github.com/{login}",
            resolved_username=login,
            fetched_at=datetime.now(timezone.utc),
        ),
        parser_metadata=ParserMetadata(analyzer_version="from_log"),
        profile=profile,
        aggregate_features=aggregate_features,
        llm_snapshot=LLMSnapshot(login=login),
        limitations=Limitations(
            notes=[l.strip("- ").strip() for l in re.findall(r"github_facts Limitations ---\n((?:  - .+\n)+)", text)[0].splitlines()]
            if "github_facts Limitations ---" in text else [],
        ),
    )

    # --- LinkedIn person ---
    person = None
    li_url = field(r"LinkedIn URL:\s+(\S+)")
    if li_url and "LINKEDIN PROFILE" in text:
        li_section = text[text.index("LINKEDIN PROFILE"):]
        about_match = re.search(r"--- About ---\n(.*?)\n\n--- Experiences", li_section, re.DOTALL)
        name_match = re.search(r"\nName:\s+(.+)", li_section)
        location_match = re.search(r"\nLocation:\s+(.+)", li_section)
        open_to_work_match = re.search(r"Open to Work:\s+(\w+)", li_section)
        person = Person(
            linkedin_url=li_url,
            name=name_match.group(1).strip() if name_match else None,
            location=location_match.group(1).strip() if location_match else None,
            about=about_match.group(1).strip() if about_match else None,
            open_to_work=(open_to_work_match.group(1) == "True") if open_to_work_match else False,
        )

    return github_facts, person, resume, login


async def main():
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("candidates/Achintya/scrape_output.log")
    github_facts, person, resume, candidate_id = parse_log(log_path)

    github_summary = build_candidate_github_summary(github_facts, person, resume) if github_facts.profile else None
    print(f"Parsed GitHub summary for login={candidate_id}, "
          f"top_technologies={github_summary.top_technologies if github_summary else []}, "
          f"person={'yes' if person else 'no'}")

    evaluator = ReadinessEvaluator()
    evaluation = await evaluator.evaluate(github_summary, person=person, resume=resume, candidate_id=candidate_id)

    out_dir = log_path.parent
    structured = evaluation.model_dump(
        exclude={"prose_report_markdown", "framework_documentation_markdown"}, mode="json"
    )
    out_path = out_dir / "readiness_evaluation.md"
    out_path.write_text(
        (evaluation.prose_report_markdown or "")
        + "\n\n## Structured Output JSON\n\n```json\n"
        + json.dumps(structured, indent=2)
        + "\n```\n"
    )
    print(f"Wrote {out_path}")

    if evaluation.framework_documentation_markdown:
        docs_dir = Path("docs")
        docs_path = docs_dir / "startup-readiness-evaluation.md"
        if not docs_path.exists():
            docs_dir.mkdir(parents=True, exist_ok=True)
            docs_path.write_text(evaluation.framework_documentation_markdown)
            print(f"Wrote {docs_path}")

    if evaluation.generation_error:
        print(f"DEGRADED: {evaluation.generation_error}")
    else:
        print(f"Overall confidence: {evaluation.overall_readiness_assessment.confidence}")
        print(f"Summary: {evaluation.overall_readiness_assessment.summary}")


if __name__ == "__main__":
    asyncio.run(main())

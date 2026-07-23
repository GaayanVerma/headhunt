#!/usr/bin/env python3
"""
Single, flag-driven entrypoint for the full candidate-enrichment pipeline:

    resume parsing -> GitHub analysis -> LinkedIn scraping -> readiness
    evaluation -> headhunt payload export (written to disk + printed)

Every stage is optional and runs only if its inputs are present and not
explicitly disabled - a candidate with only a resume, only a LinkedIn URL,
or any combination of LinkedIn/resume/GitHub is a valid run. This
consolidates samples/scrape_person.py + samples/export_to_headhunt.py into
one script so a client-facing run doesn't need two manual steps.

All API keys (LINKEDIN_EMAIL/PASSWORD, GITHUB_TOKEN, ANTHROPIC_API_KEY) are
read from .env - see .env.example. Nothing here takes a key as a CLI arg.

Usage:
    # Resume only
    python scripts/run_pipeline.py --resume path/to/resume.pdf --export-headhunt --model claude-opus-4-8

    # LinkedIn + GitHub, no resume
    python scripts/run_pipeline.py --linkedin-url https://www.linkedin.com/in/someone/ --github https://github.com/someone

    # Everything
    python scripts/run_pipeline.py --linkedin-url ... --resume ... --github ... \\
        --export-headhunt --model claude-opus-4-8

    # Skip GitHub explicitly even if the resume has a GitHub link
    python scripts/run_pipeline.py --resume path/to/resume.pdf --no-github
"""
import argparse
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Optional

from linkedin_scraper.callbacks import ConsoleCallback, SilentCallback
from linkedin_scraper.core.auth import load_anthropic_key_from_env, load_github_token_from_env
from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.evaluation import ReadinessEvaluator
from linkedin_scraper.export.headhunt_adapter import build_headhunt_payload
from linkedin_scraper.github import GitHubAIAnalyzer
from linkedin_scraper.github.candidate_summary import build_candidate_github_summary
from linkedin_scraper.resume import ResumeParser
from linkedin_scraper.scrapers.person import PersonScraper

REPO_ROOT = Path(__file__).resolve().parent.parent


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")
    return slug or "candidate"


def _resolve_candidate_id(person, github_result, resume) -> str:
    if github_result and github_result.github_facts.source_metadata.resolved_username:
        return github_result.github_facts.source_metadata.resolved_username
    if person and person.name:
        return person.name
    if resume and resume.email:
        return resume.email
    return "candidate"


def _write_artifacts(
    candidate_id: str,
    person=None,
    resume=None,
    github_result=None,
    evaluation=None,
    headhunt_payload: Optional[dict] = None,
    output_dir: Optional[Path] = None,
) -> Path:
    candidate_dir = (output_dir or REPO_ROOT / "candidates") / _slugify(candidate_id)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    if person is not None:
        (candidate_dir / "person.json").write_text(json.dumps(person.model_dump(mode="json"), indent=2))
    if resume is not None:
        (candidate_dir / "resume.json").write_text(json.dumps(resume.model_dump(mode="json"), indent=2))
    if github_result is not None:
        (candidate_dir / "github.json").write_text(
            json.dumps(github_result.github_facts.model_dump(mode="json"), indent=2)
        )
    if evaluation is not None:
        structured = evaluation.model_dump(
            exclude={"prose_report_markdown", "framework_documentation_markdown"}, mode="json"
        )
        (candidate_dir / "readiness_evaluation.md").write_text(
            (evaluation.prose_report_markdown or "")
            + "\n\n## Structured Output JSON\n\n```json\n"
            + json.dumps(structured, indent=2)
            + "\n```\n"
        )
        (candidate_dir / "readiness_evaluation.json").write_text(
            json.dumps(evaluation.model_dump(mode="json"), indent=2)
        )
    if headhunt_payload is not None:
        (candidate_dir / "headhunt_payload.json").write_text(json.dumps(headhunt_payload, indent=2))

    return candidate_dir


async def _run_resume_stage(resume_path: Optional[str]):
    if not resume_path:
        return None
    print(f"[resume] Parsing {resume_path}")
    resume = ResumeParser().parse(resume_path)
    print(f"[resume] email={resume.email} phone={resume.phone}")
    print(f"[resume] github={resume.github_url} linkedin={resume.linkedin_url}")
    if resume.other_urls:
        print(f"[resume] other_urls ({len(resume.other_urls)}):")
        for url in resume.other_urls:
            print(f"[resume]   - {url}")
    print(f"[resume] skills ({len(resume.skills)}): {', '.join(resume.skills) if resume.skills else '(none found)'}")
    print(f"[resume] projects ({len(resume.projects)}):")
    for project in resume.projects:
        print(f"[resume]   - {project.name or '(untitled)'}")
        if project.technologies:
            print(f"[resume]       tech: {', '.join(project.technologies)}")
        if project.description:
            print(f"[resume]       {project.description[:160]}{'...' if len(project.description) > 160 else ''}")
    return resume


async def _run_github_stage(
    github_url: Optional[str], include_repo_insights: bool, include_contributions: bool, callback
):
    if not github_url:
        print("[github] No GitHub URL provided or found in resume - skipping.")
        return None

    token = load_github_token_from_env()
    if not token:
        print("[github] No GITHUB_TOKEN in .env - falling back to unauthenticated REST "
              "(30-repo cap, no hygiene signals, no contribution analysis).")
    if include_repo_insights and not load_anthropic_key_from_env():
        print("[github] No ANTHROPIC_API_KEY in .env - repo insight generation will be skipped.")

    print(f"[github] Analyzing {github_url}")
    analyzer = GitHubAIAnalyzer(
        github_token=token,
        include_repo_insights=include_repo_insights,
        include_contributions=include_contributions,
        callback=callback,
    )
    result = await analyzer.analyze(github_url)
    facts = result.github_facts
    login = facts.source_metadata.resolved_username
    print(f"[github] Resolved user: {login}, repos fetched: {facts.parser_metadata.repos_fetched}")
    return result


async def _run_linkedin_stage(linkedin_url: Optional[str], session_path: str, callback):
    if not linkedin_url:
        print("[linkedin] No --linkedin-url given - skipping.")
        return None

    print(f"[linkedin] Scraping {linkedin_url}")
    async with BrowserManager(headless=False) as browser:
        await browser.load_session(session_path)
        scraper = PersonScraper(browser.page, callback=callback)
        person = await scraper.scrape(linkedin_url)
    print(f"[linkedin] name={person.name} title={person.job_title}")
    print(f"[linkedin] experiences={len(person.experiences)} educations={len(person.educations)} "
          f"accomplishments={len(person.accomplishments)} contacts={len(person.contacts)}")
    return person


async def _run_readiness_stage(person, resume, github_result, run_readiness: bool, candidate_id: str):
    if not run_readiness:
        print("[readiness] Skipped (--no-readiness).")
        return None
    if person is None and resume is None and github_result is None:
        print("[readiness] No sources available at all - skipping.")
        return None

    print("[readiness] Running startup readiness evaluation")
    github_summary = (
        build_candidate_github_summary(github_result.github_facts, person, resume)
        if github_result is not None
        else None
    )
    if github_summary is not None:
        print(f"[readiness] GitHub top technologies: {github_summary.top_technologies}")
        print(f"[readiness] Unlisted GitHub projects: {len(github_summary.unlisted_projects)}")
        if github_summary.unlisted_portfolio_url:
            print(f"[readiness] Unlisted portfolio URL: {github_summary.unlisted_portfolio_url}")
    evaluator = ReadinessEvaluator()
    evaluation = await evaluator.evaluate(
        github_result=github_summary, person=person, resume=resume, candidate_id=candidate_id
    )
    if evaluation.generation_error:
        print(f"[readiness] Degraded - generation_error: {evaluation.generation_error}")
    else:
        print(f"[readiness] overall_score={evaluation.overall_score} recommendation={evaluation.recommendation}")
    return evaluation


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--linkedin-url", help="LinkedIn profile URL to scrape (omit to skip LinkedIn entirely)")
    parser.add_argument("--session", default="linkedin_session.json", help="LinkedIn session file path")
    parser.add_argument("--resume", help="Path to PDF resume to parse")
    parser.add_argument("--github", help="GitHub profile URL (overrides the one found in the resume, if any)")
    parser.add_argument("--no-github", action="store_true", help="Skip GitHub analysis entirely")
    parser.add_argument(
        "--no-repo-insights", action="store_true",
        help="No-op: LLM-assisted repo insight generation is currently disabled entirely "
             "(see CLAUDE.md GitHub-analysis scope). Kept for CLI compatibility.",
    )
    parser.add_argument(
        "--no-contributions", action="store_true",
        help="No-op: open-source contribution analysis is currently disabled entirely "
             "(see CLAUDE.md GitHub-analysis scope). Kept for CLI compatibility.",
    )
    parser.add_argument(
        "--no-readiness", action="store_true",
        help="Skip the startup readiness evaluation stage",
    )
    parser.add_argument(
        "--export-headhunt", action="store_true",
        help="Build the final headhunt payload (requires readiness to have run)",
    )
    parser.add_argument("--model", help="Model id to record in the headhunt payload (required with --export-headhunt)")
    parser.add_argument("--output-dir", default=None, help="Directory to write candidate artifacts under (default: candidates/)")
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show internal diagnostic logging (HTTP calls, cache hits, parsing details) "
             "and per-stage progress bars, not just the [stage] summary lines",
    )
    args = parser.parse_args()

    if args.export_headhunt and not args.model:
        parser.error("--export-headhunt requires --model")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    callback = ConsoleCallback(verbose=True) if args.verbose else SilentCallback()

    resume = await _run_resume_stage(args.resume)

    github_url = args.github or (resume.github_url if resume else None)
    github_result = None
    if not args.no_github:
        github_result = await _run_github_stage(
            github_url,
            include_repo_insights=not args.no_repo_insights,
            include_contributions=not args.no_contributions,
            callback=callback,
        )
    else:
        print("[github] Skipped (--no-github).")

    person = await _run_linkedin_stage(args.linkedin_url, args.session, callback)

    candidate_id = _resolve_candidate_id(person, github_result, resume)

    evaluation = await _run_readiness_stage(
        person, resume, github_result, run_readiness=not args.no_readiness, candidate_id=candidate_id
    )

    headhunt_payload = None
    if args.export_headhunt:
        if evaluation is None:
            parser.error("--export-headhunt requires the readiness stage to have run (remove --no-readiness)")
        github_facts = github_result.github_facts if github_result else None
        headhunt_payload = build_headhunt_payload(person, resume, github_facts, evaluation, model=args.model)
        print("[export] Built headhunt payload.")

    output_dir = Path(args.output_dir) if args.output_dir else None
    candidate_dir = _write_artifacts(
        candidate_id,
        person=person,
        resume=resume,
        github_result=github_result,
        evaluation=evaluation,
        headhunt_payload=headhunt_payload,
        output_dir=output_dir,
    )

    final_payload = headhunt_payload if headhunt_payload is not None else (
        evaluation.model_dump(mode="json") if evaluation is not None else None
    )
    if final_payload is not None:
        print("\n" + "=" * 60)
        print("FINAL OUTPUT JSON")
        print("=" * 60)
        print(json.dumps(final_payload, indent=2))

    print(f"\n✓ Done. Artifacts written to {candidate_dir}")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Example: run the full candidate enrichment pipeline end to end -
resume parsing -> LinkedIn scraping -> GitHub analysis (facts + AI-assisted
repo insights + open-source contribution analysis).

All API keys (LINKEDIN_EMAIL/PASSWORD, GITHUB_TOKEN, ANTHROPIC_API_KEY) are
read from .env - see .env.example for where to get each one. Nothing here
takes a key as a CLI argument.

Usage:
    python samples/scrape_person.py
    python samples/scrape_person.py --resume linkedin_scraper/candidates/Achintya/Achintya_resume_2026.pdf
    python samples/scrape_person.py --url https://www.linkedin.com/in/someone/ --resume path/to/resume.pdf
    python samples/scrape_person.py --github https://github.com/someone
    python samples/scrape_person.py --no-linkedin --resume path/to/resume.pdf   # resume + GitHub only
    python samples/scrape_person.py --github https://github.com/someone --no-repo-insights
    python samples/scrape_person.py --github https://github.com/someone --no-contributions
"""
import argparse
import asyncio
import json
import re
from pathlib import Path
from linkedin_scraper.scrapers.person import PersonScraper
from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.core.auth import load_anthropic_key_from_env, load_github_token_from_env
from linkedin_scraper.resume import ResumeParser
from linkedin_scraper.github import GitHubAIAnalyzer
from linkedin_scraper.github.candidate_summary import build_candidate_github_summary
from linkedin_scraper.evaluation import ReadinessEvaluator


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_")
    return slug or "candidate"


def _write_readiness_output(evaluation, candidate_id: str) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    candidate_dir = repo_root / "candidates" / _slugify(candidate_id)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    structured = evaluation.model_dump(
        exclude={"prose_report_markdown", "framework_documentation_markdown"}, mode="json"
    )
    out_path = candidate_dir / "readiness_evaluation.md"
    out_path.write_text(
        (evaluation.prose_report_markdown or "")
        + "\n\n## Structured Output JSON\n\n```json\n"
        + json.dumps(structured, indent=2)
        + "\n```\n"
    )
    print(f"\n(Wrote readiness evaluation to {out_path})")

    json_path = candidate_dir / "readiness_evaluation.json"
    json_path.write_text(json.dumps(evaluation.model_dump(mode="json"), indent=2))
    print(f"(Wrote readiness evaluation JSON to {json_path})")

    if evaluation.framework_documentation_markdown:
        docs_dir = repo_root / "docs"
        docs_path = docs_dir / "startup-readiness-evaluation.md"
        if not docs_path.exists():
            docs_dir.mkdir(parents=True, exist_ok=True)
            docs_path.write_text(evaluation.framework_documentation_markdown)
            print(f"(Wrote framework documentation to {docs_path})")


def _write_pipeline_artifacts(candidate_id: str, person=None, resume_data=None, github_result=None) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    candidate_dir = repo_root / "candidates" / _slugify(candidate_id)
    candidate_dir.mkdir(parents=True, exist_ok=True)

    if person is not None:
        (candidate_dir / "person.json").write_text(json.dumps(person.model_dump(mode="json"), indent=2))
        print(f"(Wrote person JSON to {candidate_dir / 'person.json'})")
    if resume_data is not None:
        (candidate_dir / "resume.json").write_text(json.dumps(resume_data.model_dump(mode="json"), indent=2))
        print(f"(Wrote resume JSON to {candidate_dir / 'resume.json'})")
    if github_result is not None:
        (candidate_dir / "github.json").write_text(
            json.dumps(github_result.github_facts.model_dump(mode="json"), indent=2)
        )
        print(f"(Wrote github JSON to {candidate_dir / 'github.json'})")


async def run_github_analysis(github_url: str, include_repo_insights: bool, include_contributions: bool):
    token = load_github_token_from_env()
    if not token:
        print("(No GITHUB_TOKEN found in .env - falling back to unauthenticated REST, "
              "limited to 30 repos with no hygiene signals, and contribution analysis "
              "will be skipped entirely since contributionsCollection is GraphQL-only.)")
    if include_repo_insights and not load_anthropic_key_from_env():
        print("(No ANTHROPIC_API_KEY found in .env - repo insight generation will be skipped; "
              "deterministic github_facts and contribution analysis still run.)")

    analyzer = GitHubAIAnalyzer(
        github_token=token,
        include_repo_insights=include_repo_insights,
        include_contributions=include_contributions,
    )
    result = await analyzer.analyze(github_url)
    facts = result.github_facts

    print("\n" + "="*60)
    print("GITHUB ANALYSIS")
    print("="*60)
    print(f"Input URL:      {facts.source_metadata.input_url_raw}")
    print(f"Resolved user:  {facts.source_metadata.resolved_username}")
    print(f"Account type:   {facts.source_metadata.account_type}")
    print(f"Authenticated:  {facts.source_metadata.authenticated}")
    print(f"API layers:     {facts.source_metadata.api_layers_used}")

    if facts.profile is None:
        print(f"\nNo profile data available. Limitations: {facts.limitations.notes}")
        return result

    p = facts.profile
    print(f"\n--- Profile ---")
    print(f"Login:        {p.login}")
    print(f"Name:         {p.name}")
    print(f"Bio:          {p.bio}")
    print(f"Followers:    {p.followers_count}")
    print(f"Public repos: {p.public_repos_count}")

    agg = facts.aggregate_features
    print(f"\n--- Aggregate Features (deterministic_repo_signals) ---")
    print(f"Original repos:     {agg.original_repos_count} (forks excluded: {agg.forked_repos_count})")
    print(f"Active in 90d:      {agg.active_repos_90d}")
    print(f"Total stars:        {agg.total_stars}")
    print(f"Top languages:      {[l.language for l in agg.top_languages[:5]]}")
    print(f"Documentation cov:  {agg.documentation_coverage_ratio}")
    print(f"Testing coverage:   {agg.testing_coverage_ratio}")
    print(f"CI coverage:        {agg.ci_coverage_ratio}")

    if facts.limitations.notes:
        print(f"\n--- github_facts Limitations ---")
        for note in facts.limitations.notes:
            print(f"  - {note}")

    print(f"\n(LLM-assisted repo insights and open-source contribution analysis are "
          f"disabled - see CLAUDE.md GitHub-analysis scope. A trimmed GitHub summary "
          f"(top technologies, unlisted projects/portfolio) is printed once LinkedIn/"
          f"resume context is available, before readiness evaluation.)")

    return result


async def _run_readiness_evaluation(args, github_result, person, resume_data) -> None:
    if not args.readiness_evaluation:
        return
    if github_result is None:
        print("\n(No GitHub analysis result available - readiness evaluation requires --github "
              "or a resume with a github_url; skipping.)")
        return

    github_summary = build_candidate_github_summary(github_result.github_facts, person, resume_data)
    print("\n" + "="*60)
    print("GITHUB CANDIDATE SUMMARY (trimmed)")
    print("="*60)
    print(f"Top technologies:     {github_summary.top_technologies}")
    print(f"Unlisted projects:    {len(github_summary.unlisted_projects)}")
    for p in github_summary.unlisted_projects:
        print(f"  - {p.name}: {p.url}")
    print(f"Unlisted portfolio:   {github_summary.unlisted_portfolio_url}")

    print("\n" + "="*60)
    print("STARTUP READINESS EVALUATION")
    print("="*60)
    evaluator = ReadinessEvaluator()
    evaluation = await evaluator.evaluate(github_summary, person=person, resume=resume_data)
    if evaluation.generation_error:
        print(f"(Readiness evaluation degraded - generation_error: {evaluation.generation_error})")
    print(f"Overall confidence: {evaluation.overall_readiness_assessment.confidence}")
    print(f"Summary: {evaluation.overall_readiness_assessment.summary}")
    print(f"Founder takeaway: {evaluation.founder_takeaway}")
    _write_readiness_output(evaluation, evaluation.candidate_id)


async def main():
    parser = argparse.ArgumentParser(description="Run the full candidate enrichment pipeline")
    parser.add_argument(
        "--url",
        default="https://www.linkedin.com/in/gaayan-verma/",
        help="LinkedIn profile URL",
    )
    parser.add_argument("--resume", help="Path to PDF resume for additional link extraction")
    parser.add_argument("--session", default="linkedin_session.json", help="Session file path")
    parser.add_argument("--github", help="GitHub profile URL (overrides the one found in the resume, if any)")
    parser.add_argument("--no-linkedin", action="store_true", help="Skip LinkedIn scraping")
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
        "--readiness-evaluation", action="store_true",
        help="Run the founder-grade startup readiness synthesis stage after GitHub analysis "
             "(requires ANTHROPIC_API_KEY and a completed GitHub analysis; off by default)",
    )
    args = parser.parse_args()

    # --- Resume parsing (no browser needed) ---
    resume_data = None
    if args.resume:
        print(f"Parsing resume: {args.resume}")
        resume_data = ResumeParser().parse(args.resume)
        print("\n" + "="*60)
        print("RESUME")
        print("="*60)
        print(f"Email:       {resume_data.email}")
        print(f"Phone:       {resume_data.phone}")
        print(f"LinkedIn:    {resume_data.linkedin_url}")
        print(f"GitHub:      {resume_data.github_url}")
        if resume_data.other_urls:
            print("Other URLs:")
            for url in resume_data.other_urls:
                print(f"  {url}")
        if resume_data.links:
            print("All links:")
            for url in resume_data.links:
                print(f"  {url}")

    # --- GitHub analysis (no browser needed, runs independently of LinkedIn) ---
    github_result = None
    github_url = args.github or (resume_data.github_url if resume_data else None)
    if github_url and not args.no_github:
        github_result = await run_github_analysis(
            github_url,
            include_repo_insights=not args.no_repo_insights,
            include_contributions=not args.no_contributions,
        )
    elif not args.no_github:
        print("\n(No GitHub URL provided via --github or found in resume - skipping GitHub analysis.)")

    if args.no_linkedin:
        candidate_id = (
            github_result.github_facts.source_metadata.resolved_username
            if github_result and github_result.github_facts.source_metadata.resolved_username
            else "candidate"
        )
        _write_pipeline_artifacts(candidate_id, person=None, resume_data=resume_data, github_result=github_result)
        await _run_readiness_evaluation(args, github_result, person=None, resume_data=resume_data)
        print("\n✓ Done! (LinkedIn scraping skipped)")
        return

    # --- LinkedIn scraping ---
    profile_url = args.url

    async with BrowserManager(headless=False) as browser:
        await browser.load_session(args.session)
        print("✓ Session loaded")

        scraper = PersonScraper(browser.page)

        # Debug contact info page
        await browser.page.goto(profile_url + "overlay/contact-info/", wait_until="domcontentloaded")
        await asyncio.sleep(2)
        dialogs = await browser.page.locator('[data-testid="dialog-content"]').all()
        for i, d in enumerate(dialogs):
            text = await d.inner_text()
            print(f"DEBUG dialog[{i}] text: {text[:200]}")

        print(f"Scraping: {profile_url}")
        person = await scraper.scrape(profile_url)

        print("\n" + "="*60)
        print("LINKEDIN PROFILE")
        print("="*60)
        print(f"Name:         {person.name}")
        print(f"Location:     {person.location}")
        print(f"Open to Work: {person.open_to_work}")
        print(f"LinkedIn URL: {person.linkedin_url}")
        print(f"Current Title:{person.job_title}")
        print(f"Current Co:   {person.company}")
        print()
        print("--- About ---")
        print(person.about if person.about else "N/A")

        print(f"\n--- Experiences ({len(person.experiences)}) ---")
        for e in person.experiences:
            print(f"  Position:    {e.position_title}")
            print(f"  Company:     {e.institution_name}")
            print(f"  Type:        {e.employment_type}")
            print(f"  URL:         {e.linkedin_url}")
            print(f"  Dates:       {e.from_date} - {e.to_date}  ({e.duration})")
            print(f"  Location:    {e.location}")
            if e.description:
                print(f"  Description: {e.description}")
            print()

        print(f"--- Education ({len(person.educations)}) ---")
        for e in person.educations:
            print(f"  Degree:      {e.degree}")
            print(f"  Institution: {e.institution_name}")
            print(f"  URL:         {e.linkedin_url}")
            print(f"  Dates:       {e.from_date} - {e.to_date}")
            if e.description:
                print(f"  Description: {e.description}")
            print()

        print(f"--- Accomplishments ({len(person.accomplishments)}) ---")
        for a in person.accomplishments:
            print(f"  [{a.category}] {a.title}")
            if a.issuer:
                print(f"    Issuer:     {a.issuer}")
            if a.issued_date:
                print(f"    Issued:     {a.issued_date}")
            if a.credential_id:
                print(f"    Credential: {a.credential_id}")
            if a.credential_url:
                print(f"    URL:        {a.credential_url}")
            if a.description:
                print(f"    Desc:       {a.description}")
            print()

        print(f"--- Skills ({len(person.skills)}) ---")
        for s in person.skills:
            print(f"  {s}")

        print(f"\n--- Interests ({len(person.interests)}) ---")
        for i in person.interests:
            print(f"  [{i.category}] {i.name}" + (f" ({i.linkedin_url})" if i.linkedin_url else ""))

        print(f"\n--- Contacts ({len(person.contacts)}) ---")
        for c in person.contacts:
            print(f"  [{c.type}] {c.value}" + (f" ({c.label})" if c.label else ""))

        print("\n" + "="*60)

    candidate_id = (
        github_result.github_facts.source_metadata.resolved_username
        if github_result and github_result.github_facts.source_metadata.resolved_username
        else person.name
    )
    _write_pipeline_artifacts(candidate_id, person=person, resume_data=resume_data, github_result=github_result)
    await _run_readiness_evaluation(args, github_result, person=person, resume_data=resume_data)
    print("\n✓ Done!")


if __name__ == "__main__":
    asyncio.run(main())

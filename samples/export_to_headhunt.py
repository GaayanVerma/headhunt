#!/usr/bin/env python3
"""
Export a completed extract pipeline run into the JSON contract expected by
headhunt-G's ingestion endpoint (POST /api/roles/<roleId>/candidates/ingest).

This is a manual, run-once CLI (v1) - no service/queue trigger. Point it at
the JSON files already saved from a pipeline run (Person.to_json(),
ResumeData.to_json(), GitHubAnalysisResult.to_json(), and the structured
readiness JSON block from candidates/<slug>/readiness_evaluation.md), and it
writes one combined payload matching headhunt-G's candidateProfileSchema /
evaluationResultSchema.

--org-id and --role-id are required and are never invented - they must come
from an existing Better Auth organization and an existing headhunt-G role.

Usage:
    python samples/export_to_headhunt.py \\
        --org-id org_abc123 \\
        --role-id 3f6a1c2e-...  \\
        --model claude-opus-4-8 \\
        --readiness-json candidates/jane_doe/readiness_evaluation.json \\
        --person-json candidates/jane_doe/person.json \\
        --resume-json candidates/jane_doe/resume.json \\
        --github-json candidates/jane_doe/github.json \\
        --output candidates/jane_doe/headhunt_payload.json

Optionally POST it directly to a running headhunt-G dev server:
    python samples/export_to_headhunt.py ... --post http://localhost:3000/api/roles/<roleId>/candidates/ingest
"""
import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from linkedin_scraper.export.headhunt_adapter import build_headhunt_payload
from linkedin_scraper.models.github import GitHubAnalysisResult
from linkedin_scraper.models.person import Person
from linkedin_scraper.models.readiness import StartupReadinessEvaluation
from linkedin_scraper.models.resume import ResumeData


def _load_json(path: Optional[str]) -> Optional[dict]:
    if not path:
        return None
    return json.loads(Path(path).read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--org-id", required=True,
        help="Better Auth organization id (never invented) - used only to label the "
             "output file; NOT sent in the POST body, since the ingest route resolves "
             "org from the authenticated session",
    )
    parser.add_argument(
        "--role-id", required=True,
        help="Existing headhunt-G roles.id - embedded in the --post URL path "
             "(/api/roles/<roleId>/candidates/ingest), not the JSON body",
    )
    parser.add_argument("--model", required=True, help="Model id that generated the readiness evaluation")
    parser.add_argument("--readiness-json", required=True, help="Path to the structured StartupReadinessEvaluation JSON")
    parser.add_argument("--person-json", help="Path to a saved Person.to_json() output")
    parser.add_argument("--resume-json", help="Path to a saved ResumeData.to_json() output")
    parser.add_argument("--github-json", help="Path to a saved GitHubAnalysisResult.to_json() output")
    parser.add_argument("--resume-filename", help="Original resume filename, passed through as resumeFilename")
    parser.add_argument("--output", help="Path to write the combined payload JSON (default: stdout)")
    parser.add_argument("--post", help="If set, POST the payload to this headhunt-G ingest URL instead of/in addition to writing it")
    args = parser.parse_args()

    person = Person.model_validate(_load_json(args.person_json)) if args.person_json else None
    resume = ResumeData.model_validate(_load_json(args.resume_json)) if args.resume_json else None
    github_result = (
        GitHubAnalysisResult.model_validate(_load_json(args.github_json)) if args.github_json else None
    )
    evaluation = StartupReadinessEvaluation.model_validate(_load_json(args.readiness_json))

    payload = build_headhunt_payload(
        person, resume, github_result, evaluation, model=args.model
    )
    if args.resume_filename:
        payload["resumeFilename"] = args.resume_filename
    serialized = json.dumps(payload, indent=2)

    if args.output:
        Path(args.output).write_text(serialized)
        print(f"Wrote payload to {args.output}")
    else:
        print(serialized)

    if args.post:
        req = urllib.request.Request(
            args.post,
            data=serialized.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                print(f"\nPOST {args.post} -> {resp.status}")
                print(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            print(f"\nPOST {args.post} -> {e.code}")
            print(e.read().decode("utf-8"))
            raise SystemExit(1)


if __name__ == "__main__":
    main()

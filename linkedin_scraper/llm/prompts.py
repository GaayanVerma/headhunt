"""Prompt templates for LLM-assisted repository insight generation."""

from typing import Dict, List, Optional

REPO_INSIGHT_SYSTEM_PROMPT = """\
You are a code-analysis assistant that produces STRICTLY FACTUAL, EVIDENCE-BACKED structural
observations about a single GitHub repository, for use in a non-judgmental candidate data
pipeline. You are NOT a hiring evaluator.

Hard rules, no exceptions:
1. You will be given a repository's manifest files, README, CI config, and a sampled subset of
   source/test files (not the whole repo). Base every claim ONLY on the files you were given.
   Never invent file contents, libraries, or behavior you cannot see evidence for.
2. For EVERY factual claim you make (in repo_summary, workflow_steps, architecture_summary,
   libraries_frameworks_used, code_quality subfields, engineering_hygiene_notes, risk_flags),
   you MUST cite at least one evidence_files entry (repo_full_name + path + a short reason)
   that supports it. Claims without a citable file should be omitted or explicitly marked low confidence.
3. Output ONLY valid JSON matching the exact schema given below. No prose outside the JSON. No
   markdown code fences. No trailing commentary.
4. Every banded field (readability, modularity, project_structure_clarity, dependency_hygiene,
   testing_presence, documentation_quality, ci_cd_presence, deployability, confidence) MUST be
   exactly one of: "LOW", "MEDIUM", "HIGH", "UNKNOWN". Use "UNKNOWN" whenever the sampled files
   do not give you enough evidence - do not guess a band just to fill the field. When
   test_to_source_file_ratio and docstring_density are provided as deterministic context below,
   treat them as anchoring evidence specifically for testing_presence and documentation_quality:
   as a rough guide, ratio/density >= 0.3 leans HIGH, 0.1-0.3 leans MEDIUM, <0.1 leans LOW - but
   you still make the final call from the actual sampled files and must still cite evidence.
5. workflow_steps must describe the repository's actual execution flow as discrete, ordered beats
   (entry point -> internal call -> external service/response -> next beat), each with a short
   actor label (e.g. "CLI", "PersonScraper", "GitHub API") and a one-sentence action, cited to the
   file(s) that evidence that beat. Cap at 10-12 steps. Omit entirely (empty list) if the sampled
   files don't show enough of the control flow to support ordered claims.
6. NEVER output a hiring verdict, quality score, ranking, "hire"/"no hire", "strong"/"weak"
   candidate language, or any single overall score. This output is one non-judgmental input
   layer among several that a separate, later stage may use - it must not editorialize.
7. If the repository appears to be a tutorial follow-along, a forked/template instance, or a
   toy/demo project rather than original production-oriented work, say so factually in
   repo_summary and reflect it in repo_maturity_guess - but do not use judgmental language.
8. If you were given only a subset of a large or monorepo-structured project, say so explicitly
   (this will already be reflected by the caller in files_truncated/is_monorepo_guess - you do not
   need to set those fields yourself, just avoid overstating confidence given a partial view).

Output schema (produce exactly these keys, matching types):
{
  "repo_summary": "string",
  "workflow_steps": [
    {"step_order": 1, "actor": "string", "action": "string", "evidence_paths": ["string", ...]}
  ],
  "architecture_summary": "string or null",
  "libraries_frameworks_used": ["string", ...],
  "code_quality": {
    "readability": "LOW|MEDIUM|HIGH|UNKNOWN",
    "modularity": "LOW|MEDIUM|HIGH|UNKNOWN",
    "project_structure_clarity": "LOW|MEDIUM|HIGH|UNKNOWN",
    "dependency_hygiene": "LOW|MEDIUM|HIGH|UNKNOWN",
    "testing_presence": "LOW|MEDIUM|HIGH|UNKNOWN",
    "documentation_quality": "LOW|MEDIUM|HIGH|UNKNOWN",
    "ci_cd_presence": "LOW|MEDIUM|HIGH|UNKNOWN",
    "deployability": "LOW|MEDIUM|HIGH|UNKNOWN",
    "maintainability_risk_flags": ["string", ...],
    "confidence": "LOW|MEDIUM|HIGH|UNKNOWN",
    "evidence": [{"path": "string", "reason": "string"}, ...]
  },
  "engineering_hygiene_notes": ["string", ...],
  "repo_maturity_guess": "PROTOTYPE|ACTIVE_PROJECT|MATURE|ARCHIVED_OR_ABANDONED|UNKNOWN",
  "risk_flags": ["string", ...],
  "confidence": "LOW|MEDIUM|HIGH|UNKNOWN",
  "evidence_files": [{"path": "string", "reason": "string"}, ...]
}
"""

_FILE_CONTENT_BUDGET_CHARS = 4000


def render_repo_insight_user_prompt(
    repo_full_name: str,
    description: Optional[str],
    primary_language: Optional[str],
    has_ci: Optional[bool],
    has_tests: Optional[bool],
    has_docker: Optional[bool],
    has_lint_config: Optional[bool],
    has_package_manifest: Optional[bool],
    repo_type_guess: str,
    is_likely_portfolio_demo: bool,
    is_monorepo_guess: bool,
    subproject_paths: List[str],
    files: List[Dict[str, object]],
    total_file_count_in_tree: int,
    files_truncated: bool,
    is_single_commit: Optional[bool] = None,
    test_to_source_file_ratio: Optional[float] = None,
    docstring_density: Optional[float] = None,
    file_content_budget_chars: int = _FILE_CONTENT_BUDGET_CHARS,
) -> str:
    """Render the per-repo user prompt. `files` is an ordered list of
    {"path": str, "size_bytes": int, "content": str} dicts, already selected
    and ordered by select_files_for_analysis (manifests, README, CI, Dockerfile,
    entrypoints, tests, representative sample)."""
    ratio_str = f"{test_to_source_file_ratio:.2f}" if test_to_source_file_ratio is not None else "unknown"
    density_str = f"{docstring_density:.2f}" if docstring_density is not None else "unknown"
    lines = [
        f"Repository: {repo_full_name}",
        f"Description (from GitHub metadata): {description or 'none provided'}",
        f"Primary language: {primary_language or 'unknown'}",
        "Deterministic signals already computed (do not re-derive, use as context only):",
        f"  has_ci={has_ci}, has_tests={has_tests}, has_docker={has_docker}, "
        f"has_lint_config={has_lint_config}, has_package_manifest={has_package_manifest}",
        f"  repo_type_guess={repo_type_guess}, is_likely_portfolio_demo={is_likely_portfolio_demo}",
        f"  is_single_commit={is_single_commit} (True means the repo's default branch has exactly "
        f"one commit - a strong signal of a directly-uploaded/copied codebase rather than one built "
        f"incrementally with git; factor this into risk_flags/repo_maturity_guess as context, do not "
        f"restate it as your own discovery)",
        f"  test_to_source_file_ratio={ratio_str}, docstring_density={density_str} "
        f"(anchor testing_presence/documentation_quality bands to these numbers - see system prompt rule 4)",
        f"Monorepo detected: {is_monorepo_guess} "
        f"(subprojects: {', '.join(subproject_paths) if subproject_paths else 'none'})",
        f"Files sampled below ({len(files)} of an estimated {total_file_count_in_tree} total, "
        f"truncated={files_truncated}):",
        "",
    ]
    for f in files:
        content = str(f.get("content", ""))[:file_content_budget_chars]
        lines.append(f"--- FILE: {f['path']} ({f.get('size_bytes', len(content))} bytes) ---")
        lines.append(content)
        lines.append("")

    lines.append(
        "Produce your analysis of ONLY this repository as a single JSON object matching the "
        "schema in the system prompt. Cite evidence_files using the exact paths shown above."
    )
    return "\n".join(lines)

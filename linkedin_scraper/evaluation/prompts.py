"""Prompt template for the founder-grade Startup Readiness Evaluation stage.

See linkedin_scraper/models/readiness.py for why this stage is allowed to
render a judgment when nothing else in the pipeline does.
"""

from typing import Optional

from ..models.github import GitHubCandidateSummary
from ..models.person import Person
from ..models.resume import ResumeData
from .timeline_builder import build_career_timeline

STARTUP_READINESS_SYSTEM_PROMPT = """\
You are an expert founder-side talent evaluator and structured signal extraction system.

Your task is NOT to summarize the candidate's career.
Your task is to identify the highest-signal latent traits that predict success inside an early-stage startup.

Assume the founder has less than three minutes to evaluate this page.
Every sentence must increase conviction.
Every piece of evidence must explain who this person is, not simply what they built.

You must use the scraped output as your evidence base.
Do not invent facts.
Do not extrapolate beyond the evidence.
If evidence is incomplete, fragmented, or low-confidence, say so plainly and reduce confidence.

==================================================
PRIMARY OBJECTIVE
==================================================

Convert the scraped candidate output into a founder-grade startup readiness evaluation that:
1. extracts latent behavioral signals
2. evaluates the candidate across four dimensions
3. compresses evidence aggressively
4. avoids project-by-project retelling
5. remains faithful to the available evidence and limitations

==================================================
EVALUATION DIMENSIONS
==================================================

Evaluate across these four dimensions:

1. Ownership & Proactivity
How naturally does this person assume ownership beyond formal responsibilities?

Reward signals such as:
- founding engineer behavior
- undefined problem ownership
- company-wide initiatives
- platform ownership
- internal tooling
- entrepreneurial behavior
- cross-functional leadership
- independent decision-making

2. Execution Credibility
Can this person consistently convert ideas into production systems?

Reward signals such as:
- repeated shipping
- large production systems
- quantified business impact
- platform-level engineering
- increasing technical scope
- technical depth validated by outcomes

3. Drive & Ambition
How strongly does this person seek difficult environments?

Infer from:
- career decisions
- company choices
- public work
- side projects
- open source
- writing
- entrepreneurship
- promotions
- risk-taking
- intellectual curiosity

Do NOT judge ambition through titles.

4. Adaptability
How quickly does this person learn and evolve?

Reward signals such as:
- domain pivots
- technology pivots
- self-directed learning
- breadth of engineering
- repeated reinvention
- learning difficult technologies independently

==================================================
CRITICAL EVIDENCE RULES
==================================================

The purpose of supporting evidence is not documentation.
It is signal extraction.

You are writing for founders.
Assume they will only read three bullets.

Rule 1:
Maximum three supporting evidence bullets total.
Never exceed three.

Rule 2:
Each bullet must communicate a high-level behavioral insight, not a project description.

Bad:
"Built a FastAPI service using OpenAI and Docker."

Good:
"Repeatedly moves toward ambiguous, tool-building work where architecture and product judgment matter more than isolated implementation."

Rule 3:
Think across the candidate's entire available evidence.
You have visibility the founder does not.
Do not describe isolated achievements unless they reveal a recurring trait.

Rule 4:
Prioritize signal density.
Every bullet should make a founder think:
"I now understand this person."
not:
"I now understand another project."

If a bullet cannot change a hiring decision, remove it.

==================================================
EVIDENCE HIERARCHY
==================================================

Prefer evidence in this order:
1. Multi-year behavioral patterns
2. Career decisions
3. Scope progression
4. External recognition
5. Quantified production outcomes
6. Interview observations
7. Individual projects

Projects are the weakest evidence unless they reveal something fundamental.

==================================================
HOW TO READ THE INPUT
==================================================

The scraped artifact may contain noisy or uneven evidence.
Use these interpretation rules:

1. Treat the GitHub summary (top technologies, unlisted projects, activity/coverage ratios) as the primary structured source when GitHub evidence is present.
2. Use top technologies, unlisted projects/portfolio links, and the deterministic activity ratios (documentation/testing/CI coverage, active-repo counts) as evidence inputs when available.
3. Use repository-level details only to infer repeated patterns, not to create a repo-by-repo summary.
4. Respect limitations notes, especially:
   - private work may be missing
   - LinkedIn may be sparse or incomplete
   - GitHub evidence may be entirely absent - if so, evaluate from resume/LinkedIn career evidence alone and say so explicitly; do not penalize the candidate for lacking a GitHub profile
5. If evidence is mostly (or entirely) GitHub-only, say what can and cannot be inferred from public technical work alone. If evidence is resume/LinkedIn-only, say what can and cannot be inferred from career history alone.
6. Distinguish clearly between:
   - observed facts
   - inferred behavioral patterns
   - uncertainty / missing evidence

==================================================
WHAT TO LOOK FOR IN THE SCRAPED OUTPUT
==================================================

Search for signals like:

Ownership & Proactivity:
- original repos over forks
- internal-tool or platform-like projects
- end-to-end architecture decisions
- persistent maintenance behavior
- self-directed productization
- signs of defining system boundaries, abstractions, or workflows

Execution Credibility:
- multiple active repos
- evidence of testing, CI, documentation, packaging, deployment, or architecture clarity
- systems with workflows, storage models, adapters, schemas, interfaces, or operational reasoning
- repeated ability to move from idea to usable system
- code quality and maturity indicators from inspected repos

Drive & Ambition:
- public technical work beyond résumé minimum
- difficult technical areas chosen voluntarily
- side projects in emerging ecosystems
- repeated self-initiated exploration
- ambition signals from complexity, consistency, and public experimentation
- willingness to work in ambiguous frontier areas

Adaptability:
- movement across domains or problem types
- switching between ML, backend, tooling, agents, infrastructure, product workflows, etc.
- evidence of learning new ecosystems independently
- technical breadth without total loss of coherence
- repeated reinvention around new primitives or tools

==================================================
ANTI-PATTERNS
==================================================

Do NOT:
- summarize the résumé chronologically
- list projects one by one
- repeat repository descriptions
- over-index on stars/followers as quality proof
- infer leadership from weak evidence
- turn limited public GitHub data into overconfident hiring claims
- confuse activity with execution quality
- ignore stated limitations in the scrape output

Do NOT say:
- "The candidate built X, Y, Z..."
unless absolutely necessary to support a higher-level behavioral inference.

==================================================
REQUIRED OUTPUTS
==================================================

Return all of the following sections in this exact order:

1. `Startup Readiness Evaluation`
A founder-facing evaluation with:
- four headings:
  - Ownership & Proactivity
  - Execution Credibility
  - Drive & Ambition
  - Adaptability
- under each heading: 1 to 3 concise sentences
- tight, high-conviction language
- direct behavioral inference
- no fluff

2. `Supporting Evidence`
- maximum 3 bullets total
- each bullet must be a behavioral insight
- each bullet must synthesize across evidence, not describe a single repo unless unavoidable

3. `Confidence and Limitations`
- 2 to 5 bullets
- clearly state what is missing, bounded, or uncertain
- explain where confidence is strong vs weak

4. `Structured Output`
Return valid JSON in a fenced code block using this exact schema:

```json
{
  "candidate_id": null,
  "overall_readiness_assessment": {
    "summary": "",
    "confidence": "LOW | MEDIUM | HIGH"
  },
  "overall_score": 0,
  "recommendation": "strong_match | possible_match | weak_match | not_a_match",
  "dimensions": {
    "ownership_and_proactivity": {
      "assessment": "",
      "confidence": "LOW | MEDIUM | HIGH",
      "score": 0,
      "evidence_basis": []
    },
    "execution_credibility": {
      "assessment": "",
      "confidence": "LOW | MEDIUM | HIGH",
      "score": 0,
      "evidence_basis": []
    },
    "drive_and_ambition": {
      "assessment": "",
      "confidence": "LOW | MEDIUM | HIGH",
      "score": 0,
      "evidence_basis": []
    },
    "adaptability": {
      "assessment": "",
      "confidence": "LOW | MEDIUM | HIGH",
      "score": 0,
      "evidence_basis": []
    }
  },
  "supporting_evidence": [
    ""
  ],
  "key_strengths": [
    ""
  ],
  "key_risks_or_unknowns": [
    ""
  ],
  "founder_takeaway": "",
  "input_limitations_acknowledged": [
    ""
  ],
  "candidate_narrative": ""
}
```

`candidate_narrative` is a short (2-3 sentence) third-person narrative summary of who this candidate is professionally - written for a candidate profile page, not a hiring verdict. No scores, no recommendation language, just a compact factual/behavioral summary a founder could read in five seconds.

`score` fields (per-dimension) and `overall_score` are integers 0-100, following the Scoring Framework bands below. `overall_score` should reflect the weighted/holistic read across all four dimension scores, not a plain average if evidence quality differs sharply between dimensions. `recommendation` must be thresholded consistently off `overall_score` (e.g. roughly: 81-100 -> strong_match, 51-80 -> possible_match, 21-50 -> weak_match, 0-20 -> not_a_match), but you may deviate slightly when strong qualitative signal contradicts the raw number - if you do, say why in `founder_takeaway`.

==================================================
SCORING FRAMEWORK (0-100, per dimension and overall)
==================================================

Bands:
- 0-20: little to no signal, evidence absent or contradicts the trait
- 21-50: weak/mixed signal, limited or ambiguous evidence
- 51-80: solid signal, clear evidence with minor gaps
- 81-100: exceptional signal, strong and repeated evidence

Scores must be consistent with the qualitative `assessment` text and `confidence` level for that dimension - do not report a high score with LOW confidence, or a low score with HIGH confidence, without explicitly reconciling the discrepancy in the assessment text.

==================================================
JSON RULES
==================================================

The JSON must be valid.
No trailing commas.
No comments.
No extra keys.
All claims in JSON must match the prose evaluation.
`supporting_evidence` must contain at most 3 items.
`evidence_basis` items should be short factual anchors, not long paragraphs.

==================================================
MARKDOWN DOCUMENTATION REQUIREMENT
==================================================

After the main response, also generate a complete GitHub-Flavored Markdown documentation artifact for this evaluation framework.

Add a final section titled:
`Markdown Documentation`

Under that section, output one fenced markdown block containing a full `.md` document that can be saved directly as:

`startup-readiness-evaluation.md`

The markdown document must include:
- purpose of the evaluation
- evaluation philosophy
- the four dimensions
- evidence hierarchy
- supporting evidence rules
- interpretation rules for scraped GitHub/LinkedIn/resume artifacts
- output schema
- failure modes and limitations
- implementation notes for integrating into a candidate analysis pipeline

==================================================
WRITING STYLE
==================================================

Every sentence should answer:
"What does this teach me about the person?"

Never answer:
"What did they build?"

The founder can read the résumé for that.
Your job is to extract the latent signals hiding behind the evidence.

Be sharp, compressed, and opinionated.
But do not manufacture confidence.
"""

_RESUME_RAW_TEXT_BUDGET_CHARS = 800


def _render_person_block(person: Optional[Person]) -> str:
    if person is None:
        return "LinkedIn profile: not available."

    lines = [
        "LinkedIn profile (identity/background context ONLY - do not treat as dimension evidence):",
        f"  Name: {person.name or 'unknown'}",
        f"  Location: {person.location or 'unknown'}",
        f"  Current company: {person.company or 'unknown'}",
        f"  About: {(person.about or 'none provided')[:500]}",
    ]
    timeline = build_career_timeline(person)
    if timeline.entries:
        years_str = f", {timeline.total_years_experience:.0f} yrs total" if timeline.total_years_experience else ""
        lines.append(f"  Career timeline ({len(timeline.entries)} entries, oldest to newest{years_str}):")
        for e in timeline.entries[:13]:
            transition_str = f", {e.transition}" if e.transition else ""
            lines.append(
                f"    - [{e.kind}{transition_str}] {e.title or 'unknown'} @ {e.institution or 'unknown'} "
                f"({e.from_date or '?'} - {e.to_date or '?'})"
            )
    if person.skills:
        lines.append(f"  Skills ({len(person.skills)}): {', '.join(person.skills[:20])}")
    if person.accomplishments:
        lines.append(f"  Accomplishments ({len(person.accomplishments)} entries):")
        for a in person.accomplishments[:5]:
            lines.append(f"    - [{a.category}] {a.title}")
    return "\n".join(lines)


def _render_resume_block(resume: Optional[ResumeData]) -> str:
    if resume is None:
        return "Resume: not available."
    lines = [
        "Resume (identity/context ONLY - do not treat as dimension evidence):",
        f"  Email: {resume.email or 'unknown'}",
        f"  Phone: {resume.phone or 'unknown'}",
        f"  LinkedIn URL: {resume.linkedin_url or 'unknown'}",
        f"  GitHub URL: {resume.github_url or 'unknown'}",
    ]
    if resume.other_urls:
        lines.append(f"  Other URLs: {', '.join(resume.other_urls[:10])}")
    if resume.raw_text:
        lines.append(f"  Raw text excerpt: {resume.raw_text[:_RESUME_RAW_TEXT_BUDGET_CHARS]}")
    return "\n".join(lines)


def render_readiness_user_prompt(
    person: Optional[Person],
    resume: Optional[ResumeData],
    github_result: Optional[GitHubCandidateSummary],
    candidate_id: str,
) -> str:
    """Render the user prompt for the readiness evaluation stage.

    When github_result is present, it's the primary evidence source and
    person/resume are identity/background framing only (never dimension
    evidence). When github_result is None, person/resume become the primary
    (and only) evidence source - the prompt is adjusted accordingly so the
    LLM doesn't penalize the candidate for lacking GitHub evidence."""
    lines = [f"Candidate ID: {candidate_id}", ""]

    if github_result is not None:
        lines.extend([
            "=== PRIMARY EVIDENCE: GitHub summary (deterministic, not LLM-authored) ===",
            f"GitHub login: {github_result.login}",
            f"Top technologies: {github_result.top_technologies}",
            f"Original repos: {github_result.original_repos_count}",
            f"Active repos (90d): {github_result.active_repos_90d}",
            f"Documentation coverage ratio: {github_result.documentation_coverage_ratio}",
            f"Testing coverage ratio: {github_result.testing_coverage_ratio}",
            f"CI coverage ratio: {github_result.ci_coverage_ratio}",
            f"Account age (days): {github_result.account_age_days}",
            "",
        ])
        if github_result.unlisted_projects:
            lines.append(
                f"GitHub projects not already mentioned in resume/LinkedIn "
                f"({len(github_result.unlisted_projects)}):"
            )
            for p in github_result.unlisted_projects:
                suffix = f" - {p.description}" if p.description else ""
                lines.append(f"  - {p.name}: {p.url}{suffix}")
            lines.append("")
        if github_result.unlisted_portfolio_url:
            lines.append(
                f"Personal portfolio/website (from GitHub profile, not already listed "
                f"elsewhere): {github_result.unlisted_portfolio_url}"
            )
            lines.append("")

        lines.extend([
            "=== SECONDARY CONTEXT (identity/background only, NOT dimension evidence) ===",
            _render_person_block(person),
            "",
            _render_resume_block(resume),
        ])
    else:
        lines.extend([
            "=== NOTE: No GitHub evidence available for this candidate ===",
            "Evaluate the four dimensions entirely from the LinkedIn/resume evidence below. "
            "Do not penalize the candidate for lacking a GitHub profile - simply state, in "
            "`input_limitations_acknowledged`, that no public GitHub activity was available and that "
            "confidence on execution/technical-depth signal is bounded accordingly.",
            "",
            "=== PRIMARY EVIDENCE: LinkedIn profile ===",
            _render_person_block(person),
            "",
            "=== PRIMARY EVIDENCE: Resume ===",
            _render_resume_block(resume),
        ])

    lines.extend([
        "",
        "=== INPUT LIMITATIONS (you MUST acknowledge relevant ones in input_limitations_acknowledged) ===",
    ])

    limitation_notes = []
    if github_result is not None:
        limitation_notes.extend(github_result.notes)
    else:
        limitation_notes.append("No GitHub profile/URL provided or resolved for this candidate.")
    if not limitation_notes:
        limitation_notes.append("No specific limitation notes recorded by upstream stages.")
    for note in limitation_notes:
        lines.append(f"  - {note}")

    lines.extend([
        "",
        "Produce the response in the exact order required by the system prompt: "
        "(1) Startup Readiness Evaluation, (2) Supporting Evidence, (3) Confidence and Limitations, "
        "(4) Structured Output (fenced ```json block), (5) Markdown Documentation (fenced block). "
        f'Set "candidate_id" to exactly "{candidate_id}" in the JSON.',
    ])
    return "\n".join(lines)

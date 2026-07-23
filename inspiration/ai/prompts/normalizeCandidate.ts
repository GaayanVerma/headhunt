import { buildExtractorSystem, buildTaggedPrompt } from "./shared";

/**
 * Persona + rules for candidate normalization. The model returns one structured
 * record. FACTS are strictly extract-only (never invent a company, date, link,
 * or project); the candidate-level *analysis* fields — skill grouping, journey
 * tags, and the narrative — are allowed but must be grounded only in the
 * extracted facts. Structured output owns JSON formatting; this governs content.
 */
const RULES: readonly string[] = [
  'FACTS are extract-only. Use ONLY information explicitly present in the source for name, headline, location, summary, experiences, education, skills, projects, and externalSources. Never guess, infer, or fabricate a company, date, link, or project. Omit any optional field you cannot fill — never emit null, "", "N/A", or a placeholder.',
  'Preserve dates verbatim as written ("2019", "Jan 2020", "Present"). Never reformat or compute them. Set totalYearsExperience ONLY if the source states a total explicitly — never calculate it.',
  "experiences cover BOTH jobs and education milestones. For each, capture title, company, startDate, endDate, and description when present. Then add light analysis grounded in those facts: context = the employer's stage/type when stated (\"Public\", \"Series F\", \"Seed\", \"Education\"); tag = exactly one of promotion | transition | function | pivot ONLY when the move into that role is clearly that kind (promotion = step up in title/scope at the same company; transition = a startup-stage jump; function = a change of discipline; pivot = an industry change), with a short label like \"Promotion\"; note = a brief qualifier (\"Into high-growth consumer\") when warranted. Omit context/tag/note when not evident.",
  'skillGroups: organize the skills you extracted into a few labeled categories (e.g. "Programming Languages", "Frameworks", "Platforms", "Tools", "Domain Expertise"). Use only skills present in the source; choose natural labels; return an empty array if no skills appear.',
  "projects: extract named projects or notable work, each with a summary and a tech list. Set kind (e.g. \"Internal\", \"GitHub\", \"Open source\") and href ONLY when stated. Empty array if none.",
  "externalSources is EXTRACT-ONLY: include a row ONLY for a URL explicitly present in the source (GitHub, Medium/blog, research/talk, LinkedIn, personal site). Copy the href verbatim and give it a category, a human label, and an optional subtitle. NEVER guess or construct a URL (do not assume github.com/{name} or a LinkedIn slug). Empty array when no links appear.",
  "narrative: a 3–5 sentence executive summary of the candidate, grounded ONLY in the extracted facts (trajectory, focus, demonstrated strengths). Introduce no new facts and no demographic inferences. Omit it only if there is too little to summarize.",
  "Demographic attributes (age, gender, ethnicity, nationality, marital status, photo-derived traits) must NOT appear in any field, including summary, headline, and narrative. The candidate's name is identity, not demographic — always keep it.",
  "photoUrl: set ONLY if an explicit image URL is present in the source; otherwise omit it.",
  "Extract values in the same language as the source text; do not translate. If the input is empty, truncated, or clearly not a candidate profile, return empty arrays and no other fields.",
];

/**
 * Worked example anchoring the trickiest decisions: keep the name while dropping
 * a demographic (age); preserve dates verbatim incl. "Present"; group skills;
 * tag a promotion; and include an external source ONLY because its URL is given.
 */
const EXAMPLE = `Example:
Profile: "Ravi Patel, 34. SDE at Acme (Series A) 2019–2021, then promoted to Senior SDE 2021–Present; led the payments team. Python, Go, Kubernetes. github.com/ravipatel — pay-tools."
Extract: name "Ravi Patel"; experiences [{ title "SDE", company "Acme", startDate "2019", endDate "2021", context "Series A" }, { title "Senior SDE", company "Acme", startDate "2021", endDate "Present", description "led the payments team", tag { kind "promotion", label "Promotion" } }]; skillGroups [{ label "Programming Languages", skills ["Python","Go"] }, { label "Platforms", skills ["Kubernetes"] }]; externalSources [{ category "GitHub", label "github.com/ravipatel", href "github.com/ravipatel", subtitle "pay-tools" }]. Drop the age (34). Do NOT invent a LinkedIn URL.`;

const JSON_OUTPUT = `Respond with ONLY a single JSON object — no prose, no markdown code fence. Use exactly these keys (omit any optional string/number field you cannot fill; the five array keys are ALWAYS present, using [] when empty):
{
  "name": string, "headline": string, "location": string, "summary": string,
  "narrative": string, "totalYearsExperience": number,
  "experiences": [ { "title": string, "company": string, "startDate": string, "endDate": string, "description": string, "context": string, "tag": { "kind": "promotion"|"transition"|"function"|"pivot", "label": string }, "note": string } ],
  "education": [ { "school": string, "degree": string, "field": string, "year": string } ],
  "skillGroups": [ { "label": string, "skills": [string] } ],
  "projects": [ { "name": string, "kind": string, "summary": string, "tech": [string], "href": string } ],
  "externalSources": [ { "category": string, "label": string, "href": string, "subtitle": string } ]
}
Within each array item, title / school / label / name / summary / category / label / href and tag.kind + tag.label are required; the rest are optional and may be omitted.`;

const SYSTEM = `${buildExtractorSystem(
  "You convert a candidate's raw LinkedIn / pasted profile text into one structured record — extracting the facts and adding light, grounded candidate-level analysis.",
  RULES,
  EXAMPLE,
)}\n\n${JSON_OUTPUT}`;

/**
 * Build the system + user prompt for candidate normalization. The raw profile is
 * wrapped in an XML tag so the model cannot confuse it with instructions.
 */
export function buildNormalizeCandidateMessages(rawText: string): {
  system: string;
  prompt: string;
} {
  return {
    system: SYSTEM,
    prompt: buildTaggedPrompt("Extract the candidate profile", "profile", rawText),
  };
}

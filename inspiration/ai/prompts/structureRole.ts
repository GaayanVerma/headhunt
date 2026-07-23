import { buildExtractorSystem, buildTaggedPrompt } from "./shared";

/**
 * Persona + hard extraction rules for turning a free-text job description into
 * structured requirements. The model returns one structured record, so this
 * prompt only governs *what* goes into it. `title` is required, so the model must
 * always produce one; everything else is omit-don't-fabricate.
 */
const RULES: readonly string[] = [
  "title is required — use the role title stated in the job description. If no explicit title is given, use the most specific role name the responsibilities clearly support.",
  'Use ONLY information explicitly present in the description. Never fabricate requirements that are not stated. Omit any optional field you cannot fill — do not emit null, an empty string, "N/A", or a placeholder.',
  'Classify each skill by how the description frames it: required, essential, or "must have" skills go in mustHaveSkills; preferred, bonus, "nice to have", or "a plus" skills go in niceToHaveSkills. When a skill\'s importance is ambiguous, put it in niceToHaveSkills.',
  "mustHaveSkills, niceToHaveSkills, domains, and responsibilities are always arrays; use an empty array when none apply.",
  'Set minYearsExperience ONLY if the description states a minimum, as a whole number of years. Never infer it from seniority words like "senior" or "lead".',
  "Extract values in the same language as the job description; do not translate.",
  "If the input is empty, truncated, or clearly not a job description, return the best-supported title with empty mustHaveSkills, niceToHaveSkills, domains, and responsibilities arrays and no other fields.",
];

/**
 * One worked example anchoring the trickiest decisions: title from an explicit
 * name, the must-have vs nice-to-have split from signal words, and
 * minYearsExperience as a whole number. The format is intentionally informal
 * prose, not JSON — structured output owns serialization, so keep it that way.
 */
const EXAMPLE = `Example:
Job description: "Looking for a Payments Engineer. Must have 3+ years with Go and PostgreSQL. Stripe experience is a plus."
Extract: title "Payments Engineer", mustHaveSkills ["Go", "PostgreSQL"], niceToHaveSkills ["Stripe"], minYearsExperience 3.`;

const SYSTEM = buildExtractorSystem(
  "You convert a free-text job description into one structured record.",
  RULES,
  EXAMPLE,
);

/**
 * Build the system + user prompt for role structuring. The raw JD is wrapped in
 * an XML tag so the model cannot confuse it with instructions.
 */
export function buildStructureRoleMessages(rawJd: string): {
  system: string;
  prompt: string;
} {
  return {
    system: SYSTEM,
    prompt: buildTaggedPrompt(
      "Extract the structured requirements from the job description",
      "job_description",
      rawJd,
    ),
  };
}

import type { CandidateProfile } from "@/lib/domain/candidate";
import type { RoleRequirements } from "@/lib/domain/role";

/**
 * Protected-attribute suppression block + decision-support disclaimer. Kept
 * verbatim and asserted by tests — fairness guardrail for every evaluation.
 */
export const FAIRNESS_GUARDRAIL = `You MUST ignore the following candidate attributes when scoring:
- Candidate name (any nationality inferences)
- Profile photo descriptions
- Graduation year (do not use as an age proxy)
- Gender markers or pronouns in profile text
- Any characteristic protected under applicable equal-opportunity employment law

This output is a decision-support tool only. Final hiring decisions must be
made by a qualified human reviewer exercising independent judgment.`;

function list(label: string, values: string[]): string {
  return values.length ? `${label}: ${values.join(", ")}` : `${label}: (none stated)`;
}

function formatRole(role: RoleRequirements): string {
  const lines = [
    `Title: ${role.title}`,
    role.seniority ? `Seniority: ${role.seniority}` : null,
    list("Must-have skills", role.mustHaveSkills),
    list("Nice-to-have skills", role.niceToHaveSkills),
    role.minYearsExperience != null
      ? `Minimum years of experience: ${role.minYearsExperience}`
      : null,
    list("Domains", role.domains),
    list("Responsibilities", role.responsibilities),
    role.location ? `Location: ${role.location}` : null,
  ];
  return lines.filter(Boolean).join("\n");
}

function formatCandidate(candidate: CandidateProfile): string {
  const experiences = candidate.experiences.map((exp) => {
    const where = exp.company ? ` @ ${exp.company}` : "";
    const when =
      exp.startDate || exp.endDate
        ? ` (${exp.startDate ?? "?"}–${exp.endDate ?? "present"})`
        : "";
    const desc = exp.description ? `\n    ${exp.description}` : "";
    return `  - ${exp.title}${where}${when}${desc}`;
  });
  const education = candidate.education.map((edu) => {
    const detail = [edu.degree, edu.field].filter(Boolean).join(", ");
    return `  - ${edu.school}${detail ? ` — ${detail}` : ""}${edu.year ? ` (${edu.year})` : ""}`;
  });

  const lines = [
    candidate.name ? `Name: ${candidate.name}` : null,
    candidate.headline ? `Headline: ${candidate.headline}` : null,
    candidate.location ? `Location: ${candidate.location}` : null,
    candidate.totalYearsExperience != null
      ? `Total years of experience: ${candidate.totalYearsExperience}`
      : null,
    candidate.summary ? `Summary: ${candidate.summary}` : null,
    list("Skills", candidate.skillGroups.flatMap((g) => g.skills)),
    experiences.length ? `Experience:\n${experiences.join("\n")}` : "Experience: (none stated)",
    education.length ? `Education:\n${education.join("\n")}` : "Education: (none stated)",
  ];
  return lines.filter(Boolean).join("\n");
}

/** Build the system + user messages for a full evaluation. */
export function buildEvaluationMessages(
  role: RoleRequirements,
  candidate: CandidateProfile,
): { system: string; prompt: string } {
  const system = `You are a structured candidate evaluator assisting a startup founder. Assess the candidate's STARTUP READINESS on four dimensions, each an integer 0–100 with a one-line summary and 1–3 supporting-evidence bullets:
- ownership — Ownership & Proactivity: drives initiatives and owns outcomes rather than waiting to be told.
- ambition — Ambition / Hunger / Drive: seeks growth, higher-leverage scope, and faster-paced environments.
- execution — Execution & Growth Velocity: ships, grows scope, and compounds impact over time.
- learnability — Learnability & Adaptability: picks up new tools and domains quickly; comfortable with ambiguity.
Then give an overall integer readiness score 0–100 and a recommendation tier (strong_match, possible_match, weak_match, not_a_match) for THIS role. Base every score and bullet only on the role requirements and candidate evidence below. Every evidence bullet MUST be grounded in the candidate text — never invent one. Do not reward or penalise missing optional information beyond what it implies about fit.

${FAIRNESS_GUARDRAIL}

Return your verdict as the structured object: an overall \`overallScore\`, a \`recommendation\`, and a \`readiness\` array of the four dimensions (each with dimension, score, summary, evidence).`;

  const prompt = `Evaluate this candidate against this role.\n\n# Role\n${formatRole(role)}\n\n# Candidate\n${formatCandidate(candidate)}`;

  return { system, prompt };
}

/** Build the lightweight system + user messages for the cheap pre-screen pass. */
export function buildPrescreenMessages(
  role: RoleRequirements,
  candidate: CandidateProfile,
): { system: string; prompt: string } {
  const system = `You are a fast recruiting pre-screen. Decide only whether this candidate is plausibly worth a full evaluation for the role. Set proceed=false ONLY when the candidate is clearly in the wrong field or clearly lacks the core requirements; when in doubt, set proceed=true.

${FAIRNESS_GUARDRAIL}

Return your decision as the structured object.`;

  const prompt = `# Role\n${formatRole(role)}\n\n# Candidate\n${formatCandidate(candidate)}`;

  return { system, prompt };
}

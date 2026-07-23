import { z } from "zod";
import type { CandidateProfile } from "@/lib/domain/candidate";
import {
  evaluationResultSchema,
  RECOMMENDATIONS,
  type EvaluationResult,
} from "@/lib/domain/evaluation";
import { READINESS_DIMENSIONS } from "@/lib/domain/profile";
import type { RoleRequirements } from "@/lib/domain/role";
import { generateStructured } from "./generateStructured";
import { model, prescreenModel } from "./provider";
import { buildEvaluationMessages, buildPrescreenMessages } from "./prompt";

const prescreenSchema = z.object({ proceed: z.boolean() });

// Lenient schema for the model call: scores uncapped so `clampEvaluation` can
// repair out-of-range values before strict validation, rather than forcing a retry.
const lenientScore = z.number();
const lenientEvaluationSchema = z.object({
  overallScore: lenientScore,
  recommendation: z.enum(RECOMMENDATIONS),
  readiness: z.array(
    z.object({
      dimension: z.enum(READINESS_DIMENSIONS),
      score: lenientScore,
      summary: z.string(),
      evidence: z.array(z.string()).default([]),
    }),
  ),
});

function clamp(n: number): number {
  return Math.max(0, Math.min(100, Math.round(n)));
}

/** Clamp/round scores into the schema's integer 0–100 range before validation. */
function clampEvaluation(raw: unknown): unknown {
  if (!raw || typeof raw !== "object") return raw;
  const r = raw as Record<string, unknown>;
  const out: Record<string, unknown> = { ...r };
  if (typeof r.overallScore === "number") out.overallScore = clamp(r.overallScore);
  if (Array.isArray(r.readiness)) {
    out.readiness = r.readiness.map((d) => {
      if (!d || typeof d !== "object") return d;
      const dim = d as Record<string, unknown>;
      return typeof dim.score === "number" ? { ...dim, score: clamp(dim.score) } : dim;
    });
  }
  return out;
}

const PRESCREEN_REJECTION: EvaluationResult = {
  overallScore: 0,
  recommendation: "not_a_match",
  readiness: READINESS_DIMENSIONS.map((dimension) => ({
    dimension,
    score: 0,
    summary: "Pre-screen: clearly outside role requirements.",
    evidence: [],
  })),
};

async function shouldProceed(
  role: RoleRequirements,
  candidate: CandidateProfile,
): Promise<boolean> {
  if (!prescreenModel) return true;
  const { system, prompt } = buildPrescreenMessages(role, candidate);
  const { proceed } = await generateStructured({
    model: prescreenModel,
    schema: prescreenSchema,
    system,
    prompt,
  });
  return proceed;
}

/**
 * Evaluate a candidate against a role into a validated {@link EvaluationResult}
 * (overall readiness + the four startup-readiness dimensions). Optionally runs a
 * cheap pre-screen (when `ANTHROPIC_PRESCREEN_MODEL` is set) that short-circuits
 * clear non-matches before the full evaluation.
 */
export async function evaluate(
  role: RoleRequirements,
  candidate: CandidateProfile,
): Promise<EvaluationResult> {
  if (prescreenModel) {
    const proceed = await shouldProceed(role, candidate);
    if (!proceed) return PRESCREEN_REJECTION;
  }

  const { system, prompt } = buildEvaluationMessages(role, candidate);
  return generateStructured({
    model,
    schema: evaluationResultSchema,
    genSchema: lenientEvaluationSchema,
    normalize: clampEvaluation,
    system,
    prompt,
  });
}

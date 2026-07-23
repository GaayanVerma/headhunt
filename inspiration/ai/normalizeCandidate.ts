import {
  candidateProfileSchema,
  type CandidateProfile,
} from "@/lib/domain/candidate";
import { generateStructured } from "./generateStructured";
import { model } from "./provider";
import { CandidateNormalizationError } from "./errors";
import { buildNormalizeCandidateMessages } from "./prompts/normalizeCandidate";

/**
 * Normalize raw LinkedIn export / pasted profile text into a validated
 * {@link CandidateProfile} using Claude via the Vercel AI SDK with
 * schema-constrained structured output. Throws
 * {@link CandidateNormalizationError} if the model never produces a conforming
 * response.
 */
export async function normalizeCandidate(
  rawText: string,
): Promise<CandidateProfile> {
  const { system, prompt } = buildNormalizeCandidateMessages(rawText);
  return generateStructured({
    model,
    schema: candidateProfileSchema,
    json: true, // rich schema exceeds Anthropic's grammar limits; generate plain JSON
    system,
    prompt,
    onError: (issues) => new CandidateNormalizationError(issues),
  });
}

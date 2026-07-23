import type { z } from "zod";

/** The Zod issues that explain why a model response was rejected. */
export type ZodIssues = z.ZodError["issues"];

/** Claude's candidate-normalization output failed schema validation after retries. */
export class CandidateNormalizationError extends Error {
  constructor(public readonly issues: ZodIssues) {
    super("Claude response failed CandidateProfile schema after retries");
    this.name = "CandidateNormalizationError";
  }
}

/** Claude's role-structuring output failed schema validation after retries. */
export class RoleStructuringError extends Error {
  constructor(public readonly issues: ZodIssues) {
    super("Claude response failed RoleRequirements schema after retries");
    this.name = "RoleStructuringError";
  }
}

/** The evaluation model never produced a schema-valid result within the retry budget. */
export class EvaluationEngineError extends Error {
  constructor(
    public readonly issues: ZodIssues = [],
    message = "Evaluation failed schema validation after retries",
  ) {
    super(message);
    this.name = "EvaluationEngineError";
  }
}

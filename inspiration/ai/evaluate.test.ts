import { beforeEach, describe, expect, it, vi } from "vitest";

const { generateText } = vi.hoisted(() => ({ generateText: vi.fn() }));
vi.mock("ai", () => ({ generateText, Output: { object: (c: unknown) => c } }));
vi.mock("@ai-sdk/anthropic", () => ({ anthropic: () => ({}) }));
vi.mock("@/lib/env", () => ({
  env: { ANTHROPIC_MODEL: "test-model", ANTHROPIC_API_KEY: "k" },
}));

import { EvaluationEngineError } from "./errors";
import { evaluate } from "./evaluate";
import { buildEvaluationMessages, FAIRNESS_GUARDRAIL } from "./prompt";

const role = {
  title: "Backend Engineer",
  mustHaveSkills: ["Go"],
  niceToHaveSkills: [],
  domains: [],
  responsibilities: [],
};
const candidate = {
  experiences: [],
  education: [],
  skillGroups: [{ label: "Languages", skills: ["Go"] }],
  projects: [],
  externalSources: [],
};

const READINESS = ["ownership", "ambition", "execution", "learnability"].map((dimension) => ({
  dimension,
  score: 80,
  summary: "Strong signal.",
  evidence: ["Deep Go experience"],
}));
const validResult = {
  overallScore: 82,
  recommendation: "strong_match",
  readiness: READINESS,
};

describe("evaluate", () => {
  beforeEach(() => generateText.mockReset());

  it("returns an EvaluationResult for a valid model response", async () => {
    generateText.mockResolvedValueOnce({ output: validResult });

    const result = await evaluate(role, candidate);

    expect(result.overallScore).toBe(82);
    expect(result.recommendation).toBe("strong_match");
    expect(result.readiness).toHaveLength(4);
    expect(generateText).toHaveBeenCalledTimes(1);
  });

  it("clamps out-of-range scores into [0, 100]", async () => {
    generateText.mockResolvedValueOnce({
      output: {
        ...validResult,
        overallScore: 150,
        readiness: [
          { dimension: "ownership", score: 120, summary: "x", evidence: [] },
          ...READINESS.slice(1),
        ],
      },
    });

    const result = await evaluate(role, candidate);

    expect(result.overallScore).toBe(100);
    expect(result.readiness[0].score).toBe(100);
  });

  it("throws EvaluationEngineError when the model output fails validation", async () => {
    generateText.mockResolvedValueOnce({ output: { recommendation: "strong_match" } });

    await expect(evaluate(role, candidate)).rejects.toBeInstanceOf(EvaluationEngineError);
  });

  it("throws EvaluationEngineError when generation fails outright", async () => {
    generateText.mockRejectedValueOnce(new Error("no object generated"));

    await expect(evaluate(role, candidate)).rejects.toBeInstanceOf(EvaluationEngineError);
  });

  it("includes the fairness guardrail in the system prompt", () => {
    const { system } = buildEvaluationMessages(role, candidate);

    expect(system).toContain(FAIRNESS_GUARDRAIL);
    expect(system).toContain("decision-support tool only");
  });
});

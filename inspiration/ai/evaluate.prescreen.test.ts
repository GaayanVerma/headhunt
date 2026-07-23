import { beforeEach, describe, expect, it, vi } from "vitest";

const { generateText } = vi.hoisted(() => ({ generateText: vi.fn() }));
vi.mock("ai", () => ({ generateText, Output: { object: (c: unknown) => c } }));
vi.mock("@ai-sdk/anthropic", () => ({ anthropic: () => ({}) }));
vi.mock("@/lib/env", () => ({
  env: {
    ANTHROPIC_MODEL: "test-model",
    ANTHROPIC_PRESCREEN_MODEL: "test-haiku",
    ANTHROPIC_API_KEY: "k",
  },
}));

import { evaluate } from "./evaluate";

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

const validResult = {
  overallScore: 82,
  recommendation: "strong_match",
  readiness: ["ownership", "ambition", "execution", "learnability"].map((dimension) => ({
    dimension,
    score: 80,
    summary: "Fit.",
    evidence: [],
  })),
};

describe("evaluate with pre-screen", () => {
  beforeEach(() => generateText.mockReset());

  it("skips the full evaluation when the pre-screen rejects", async () => {
    generateText.mockResolvedValueOnce({ output: { proceed: false } });

    const result = await evaluate(role, candidate);

    expect(result.recommendation).toBe("not_a_match");
    expect(result.overallScore).toBe(0);
    expect(generateText).toHaveBeenCalledTimes(1); // only the pre-screen call ran
  });

  it("runs the full evaluation when the pre-screen passes", async () => {
    generateText
      .mockResolvedValueOnce({ output: { proceed: true } })
      .mockResolvedValueOnce({ output: validResult });

    const result = await evaluate(role, candidate);

    expect(result.overallScore).toBe(82);
    expect(generateText).toHaveBeenCalledTimes(2);
  });
});

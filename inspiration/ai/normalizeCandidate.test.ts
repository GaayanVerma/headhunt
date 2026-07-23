import { beforeEach, describe, expect, it, vi } from "vitest";

const { generateText } = vi.hoisted(() => ({ generateText: vi.fn() }));
vi.mock("ai", () => ({ generateText, Output: { object: (c: unknown) => c } }));
vi.mock("@ai-sdk/anthropic", () => ({ anthropic: () => ({}) }));
vi.mock("@/lib/env", () => ({
  env: { ANTHROPIC_MODEL: "test-model", ANTHROPIC_API_KEY: "k" },
}));

import { CandidateNormalizationError } from "./errors";
import { normalizeCandidate } from "./normalizeCandidate";
import { buildNormalizeCandidateMessages } from "./prompts/normalizeCandidate";

const validProfile = {
  name: "Ada Okonkwo",
  headline: "Staff Engineer",
  skillGroups: [{ label: "Languages", skills: ["Go", "PostgreSQL"] }],
  experiences: [{ title: "Staff Engineer", company: "Acme" }],
  education: [{ school: "MIT" }],
};

describe("normalizeCandidate", () => {
  beforeEach(() => generateText.mockReset());

  it("returns a CandidateProfile for a valid response", async () => {
    generateText.mockResolvedValueOnce({ text: JSON.stringify(validProfile) });

    const profile = await normalizeCandidate("Ada Okonkwo — Staff Engineer");

    expect(profile.name).toBe("Ada Okonkwo");
    expect(profile.skillGroups[0].skills).toEqual(["Go", "PostgreSQL"]);
  });

  it("applies array defaults for a sparse profile", async () => {
    generateText.mockResolvedValueOnce({ text: JSON.stringify({ name: "Solo" }) });

    const profile = await normalizeCandidate("...");

    expect(profile.skillGroups).toEqual([]);
    expect(profile.experiences).toEqual([]);
    expect(profile.education).toEqual([]);
  });

  it("throws CandidateNormalizationError when the output fails validation", async () => {
    generateText.mockResolvedValueOnce({ text: JSON.stringify({ skillGroups: "not-an-array" }) });

    await expect(normalizeCandidate("...")).rejects.toBeInstanceOf(
      CandidateNormalizationError,
    );
  });

  it("throws CandidateNormalizationError when generation fails outright", async () => {
    generateText.mockRejectedValueOnce(new Error("no object generated"));

    await expect(normalizeCandidate("...")).rejects.toBeInstanceOf(
      CandidateNormalizationError,
    );
  });

  it("wraps the raw text in a <profile> tag and carries the extraction rules", () => {
    const { system, prompt } = buildNormalizeCandidateMessages("RAW_INPUT_XYZ");

    expect(prompt).toContain("<profile>");
    expect(prompt).toContain("RAW_INPUT_XYZ");
    expect(system.toLowerCase()).toContain("demographic");
    expect(system).toContain("structured record");
  });
});

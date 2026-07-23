import { beforeEach, describe, expect, it, vi } from "vitest";

const { generateText } = vi.hoisted(() => ({ generateText: vi.fn() }));
vi.mock("ai", () => ({ generateText, Output: { object: (c: unknown) => c } }));
vi.mock("@ai-sdk/anthropic", () => ({ anthropic: () => ({}) }));
vi.mock("@/lib/env", () => ({
  env: { ANTHROPIC_MODEL: "test-model", ANTHROPIC_API_KEY: "k" },
}));

import { RoleStructuringError } from "./errors";
import { structureRole } from "./structureRole";
import { buildStructureRoleMessages } from "./prompts/structureRole";

describe("structureRole", () => {
  beforeEach(() => generateText.mockReset());

  it("returns RoleRequirements for a valid response and applies array defaults", async () => {
    generateText.mockResolvedValueOnce({
      output: { title: "Backend Engineer", mustHaveSkills: ["Go"] },
    });

    const requirements = await structureRole("We need a Go backend engineer.");

    expect(requirements.title).toBe("Backend Engineer");
    expect(requirements.mustHaveSkills).toEqual(["Go"]);
    expect(requirements.niceToHaveSkills).toEqual([]);
    expect(requirements.domains).toEqual([]);
  });

  it("throws RoleStructuringError when the response is missing the required title", async () => {
    generateText.mockResolvedValueOnce({ output: { mustHaveSkills: [] } });

    await expect(structureRole("...")).rejects.toBeInstanceOf(RoleStructuringError);
  });

  it("throws RoleStructuringError when generation fails outright", async () => {
    generateText.mockRejectedValueOnce(new Error("no object generated"));

    await expect(structureRole("...")).rejects.toBeInstanceOf(RoleStructuringError);
  });

  it("wraps the raw JD in a <job_description> tag and carries the extraction rules", () => {
    const { system, prompt } = buildStructureRoleMessages("RAW_JD_XYZ");

    expect(prompt).toContain("<job_description>");
    expect(prompt).toContain("RAW_JD_XYZ");
    expect(system.toLowerCase()).toContain("minyearsexperience");
    expect(system).toContain("structured record");
  });
});

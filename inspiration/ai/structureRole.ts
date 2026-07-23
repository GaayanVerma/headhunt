import {
  roleRequirementsSchema,
  type RoleRequirements,
} from "@/lib/domain/role";
import { generateStructured } from "./generateStructured";
import { model } from "./provider";
import { RoleStructuringError } from "./errors";
import { buildStructureRoleMessages } from "./prompts/structureRole";

/**
 * Convert a raw pasted job description into validated {@link RoleRequirements}
 * using Claude via the Vercel AI SDK with schema-constrained structured output.
 * Throws {@link RoleStructuringError} if the model never produces a conforming
 * response.
 */
export async function structureRole(rawJd: string): Promise<RoleRequirements> {
  const { system, prompt } = buildStructureRoleMessages(rawJd);
  return generateStructured({
    model,
    schema: roleRequirementsSchema,
    system,
    prompt,
    onError: (issues) => new RoleStructuringError(issues),
  });
}

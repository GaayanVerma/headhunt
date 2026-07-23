import { generateText, Output, type LanguageModel } from "ai";
import type { z } from "zod";
import { EvaluationEngineError, type ZodIssues } from "./errors";

export interface GenerateStructuredArgs<T> {
  model: LanguageModel;
  /** Strict schema the final result must satisfy. */
  schema: z.ZodType<T>;
  system: string;
  prompt: string;
  /**
   * Looser schema for the model call (defaults to `schema`). Lets `normalize`
   * repair clampable values before strict validation rather than forcing a retry.
   */
  genSchema?: z.ZodTypeAny;
  /** Optional pre-validation transform (e.g. clamp numeric ranges). */
  normalize?: (raw: unknown) => unknown;
  /** Maps a failure to a domain-specific error. Defaults to EvaluationEngineError. */
  onError?: (issues: ZodIssues) => Error;
  /**
   * Generate free-form JSON and parse it instead of using the SDK's constrained
   * `Output.object`. Needed for rich schemas that exceed Anthropic's grammar
   * limits (optional-parameter cap / "schema too complex"). The prompt must
   * instruct the model to emit a single JSON object.
   */
  json?: boolean;
}

/** Extract the outermost JSON object from a model response (tolerates code fences/prose). */
function parseJsonObject(text: string): unknown {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const body = fenced ? fenced[1] : text;
  const start = body.indexOf("{");
  const end = body.lastIndexOf("}");
  if (start === -1 || end <= start) throw new Error("no JSON object in response");
  return JSON.parse(body.slice(start, end + 1));
}

/**
 * Structured generation against Claude via the Vercel AI SDK (`generateText` +
 * `Output.object`). The SDK constrains and repairs the model output to the
 * schema; we then optionally `normalize` and validate against the strict
 * `schema`. Any failure is mapped to a domain error via `onError`.
 */
export async function generateStructured<T>({
  model,
  schema,
  system,
  prompt,
  genSchema,
  normalize,
  onError,
  json,
}: GenerateStructuredArgs<T>): Promise<T> {
  const fail = (issues: ZodIssues): Error =>
    onError ? onError(issues) : new EvaluationEngineError(issues);

  let raw: unknown;
  try {
    if (json) {
      const { text } = await generateText({ model, system, prompt, temperature: 0 });
      raw = parseJsonObject(text);
    } else {
      const { output } = await generateText({
        model,
        system,
        prompt,
        temperature: 0,
        output: Output.object({ schema: (genSchema ?? schema) as z.ZodTypeAny }),
      });
      raw = output;
    }
  } catch {
    // Model never produced parseable/schema-valid output within the retry budget.
    throw fail([]);
  }

  const result = schema.safeParse(normalize ? normalize(raw) : raw);
  if (result.success) return result.data;
  throw fail(result.error.issues);
}

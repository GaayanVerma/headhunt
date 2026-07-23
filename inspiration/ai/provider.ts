import { anthropic } from "@ai-sdk/anthropic";
import { env } from "@/lib/env";

/**
 * Anthropic models via the Vercel AI SDK. The provider reads `ANTHROPIC_API_KEY`
 * from the environment. Server-only — never import from a Client Component.
 */
export const model = anthropic(env.ANTHROPIC_MODEL);

/** Optional cheaper model for the pre-screen pass; null when unconfigured. */
export const prescreenModel = env.ANTHROPIC_PRESCREEN_MODEL
  ? anthropic(env.ANTHROPIC_PRESCREEN_MODEL)
  : null;

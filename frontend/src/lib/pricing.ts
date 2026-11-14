// Gemini 2.5 Flash standard pricing in USD per million tokens.
const GEMINI_USD_PER_MTOK = {
  input: 0.3,
  output: 2.5,
  cacheRead: 0.03,
};

// Prisma programme credits do not have a universal published price card.
// Server-side ledger values are authoritative. This only supports the legacy
// admin estimate when an older endpoint returns aggregate usage.
const GNANI_USD_PER_MIN = 0;

export const FALLBACK_USD_TO_INR = 94;

// Reuses the API response shape directly rather than redefining it here —
// the two drifted out of sync once already when duration_minutes was added.
export type { AIUsage } from "@/lib/api";
import type { AIUsage } from "@/lib/api";

export function gnaniCostUsd(durationMinutes: number, transcriptionRequests: number): number {
  if (transcriptionRequests <= 0) return 0;
  return durationMinutes * GNANI_USD_PER_MIN;
}

// Total cost across every API actually called for a meeting: Gemini
// (extraction + any contradiction checks) plus Prisma (transcription).
export function usageCostInr(usage: AIUsage, usdToInr = FALLBACK_USD_TO_INR): number {
  const geminiUsd =
    (usage.input_tokens / 1_000_000) * GEMINI_USD_PER_MTOK.input +
    (usage.output_tokens / 1_000_000) * GEMINI_USD_PER_MTOK.output +
    (usage.cache_tokens_read / 1_000_000) * GEMINI_USD_PER_MTOK.cacheRead;
  return (geminiUsd + gnaniCostUsd(usage.duration_minutes, usage.transcription_requests)) * usdToInr;
}

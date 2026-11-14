// Gemini 2.5 Flash standard pricing in USD per million tokens.
const GEMINI_USD_PER_MTOK = {
  input: 0.3,
  output: 2.5,
  cacheRead: 0.03,
};

// Deepgram pricing, confirmed against deepgram.com/pricing (2026-07) for
// what transcriber.py actually requests: Nova-3 with language=multi
// (Hindi+English code-switching) plus diarize_model=latest. Keyterm
// prompting, smart_format, and utterances are included at no extra cost.
const DEEPGRAM_USD_PER_MIN = {
  nova3Multilingual: 0.0092,
  diarization: 0.002,
};

export const FALLBACK_USD_TO_INR = 94;

// Reuses the API response shape directly rather than redefining it here —
// the two drifted out of sync once already when duration_minutes was added.
export type { AIUsage } from "@/lib/api";
import type { AIUsage } from "@/lib/api";

export function deepgramCostUsd(durationMinutes: number, transcriptionRequests: number): number {
  if (transcriptionRequests <= 0) return 0;
  return durationMinutes * (DEEPGRAM_USD_PER_MIN.nova3Multilingual + DEEPGRAM_USD_PER_MIN.diarization);
}

// Total cost across every API actually called for a meeting: Gemini
// (extraction + any contradiction checks) plus Deepgram (transcription).
export function usageCostInr(usage: AIUsage, usdToInr = FALLBACK_USD_TO_INR): number {
  const geminiUsd =
    (usage.input_tokens / 1_000_000) * GEMINI_USD_PER_MTOK.input +
    (usage.output_tokens / 1_000_000) * GEMINI_USD_PER_MTOK.output +
    (usage.cache_tokens_read / 1_000_000) * GEMINI_USD_PER_MTOK.cacheRead;
  return (geminiUsd + deepgramCostUsd(usage.duration_minutes, usage.transcription_requests)) * usdToInr;
}

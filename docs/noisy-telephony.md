# Noisy telephone audio: implementation and evaluation

Introduced in [PR #18](https://github.com/testing-archit/bhadra/pull/18). Benchmark audio is synthetic, not an award result or a real-call acceptance test. Release checks are recorded in `docs/coordination.md`.

## What the audit found

The deployed implementation at `d184828` uses Gnani Prisma v3 REST, despite older architecture notes naming Whisper/Deepgram. Short WebM recordings are remuxed into Ogg. Longer recordings are re-encoded to 16 kHz mono Opus and split at fixed 25-second boundaries. The source waveform is not analyzed for boundaries, and the multipart fields include `key_terms`, `mode` and `format` together.

Current [Gnani REST documentation](https://docs.gnani.ai/api/STT/speech-to-text) specifies `keyterms` and `format`, accepts a previous clip's text, and supports language hints. Those request fields are corrected. Hinglish hints Hindi and English; Auto still requests automatic language detection. The documented [REST limit](https://docs.gnani.ai/api/STT/limits) remains 30 seconds, so individual uploads stay below it.

## Research and implementation choices

| Evidence | Decision |
| --- | --- |
| [Google ASR guidance](https://docs.cloud.google.com/speech-to-text/docs/best-practices) recommends native sample rates, lossless encoding and separate channels when speakers are separately recorded; it warns that denoising can reduce recognition accuracy. | Decode once to PCM16, preserve sample rate/channels, avoid automatic gain and another lossy codec. Expose explicit separate-channel handling for genuine caller/agent tracks. |
| [RNNoise](https://github.com/xiph/rnnoise) offers lightweight recurrent noise suppression; [FFmpeg](https://ffmpeg.org/ffmpeg-filters.html#arnndn) exposes it with an input/output mix. | Optional local neural enhancement with a 65% wet mix and original-PCM fallback. No model download at application runtime. |
| [DeepFilterNet](https://github.com/Rikorose/DeepFilterNet) targets efficient full-band enhancement; [Silero VAD](https://github.com/snakers4/silero-vad) supports 8/16 kHz activity detection. | Evaluated as alternatives, not installed or claimed implemented. Neither listening quality nor VAD alone establishes telephony recognition accuracy. |
| [Microsoft DNS Challenge](https://github.com/microsoft/DNS-Challenge) evaluates both speech/background quality and word accuracy. | Measure WER, CER, critical-phrase recall, noise-only insertions and latency; retain per-clip evidence. |
| [ElevenLabs Scribe v3](https://elevenlabs.io/docs/overview/models) supports multilingual transcription and word timestamps. | After a direct comparison, add an explicit `robust` transcription profile using Scribe v3. This uses the frontier model, rather than claiming a new model surpasses it. |

## Runtime behavior

- `standard` remains the default, using Gnani and the improved PCM preparation.
- `robust` selects Scribe v3 directly. No automatic paid cascade, voting, or speculative second transcription. It uses original PCM without optional denoisers.
- Long audio is read in bounded windows. Cuts prefer a nearby quiet valley between 22 and 27 seconds, otherwise 25 seconds. Every sample is retained exactly once; this is not a speech detector. Continuous speech can still cross a fallback cut.
- Only exactly zero PCM windows skip ASR. Quiet speech is retained. Pure background noise still reaches ASR; the benchmark measures resulting hallucinations.
- `audio_channel_mode=separate` is explicit: each input channel is transcribed on the same timeline with stable channel IDs. Use only for one party per track. Stereo music/duplicated microphones should use `preserve`.
- Provider speaker IDs remain local to a chunk; labels are not assumed to identify the same person across separate calls. Existing caption/enrolled-voice matching remains responsible for identity. Missing speaker confidence is not invented.
- Word timestamps are retained and offset back onto the original timeline. Malformed audio returns HTTP 422. FFmpeg is killed/reaped on cancellation; temporary PCM is removed. Media demuxers and protocols are restricted, and decoded duration/size are bounded.
- Each successful transcription chunk enters the cost ledger immediately, even if a subsequent chunk fails. Provider response bodies containing possible transcript content are not logged in exceptions.

Configuration:

```dotenv
STT_PROFILE=standard
STT_ENHANCEMENT=off
STT_PREVIOUS_CONTEXT=true
ELEVEN_LABS_API_KEY=
# Only required for optional RNNoise experimentation:
STT_RNNOISE_MODEL_PATH=/models/std.rnnn
```

For an individual authenticated `POST /api/meetings/ingest` upload, set `transcription_profile=robust`. Set `STT_PROFILE=robust` on a configured backend to select it for central transcription callers, including the notetaker. The Gnani lab remains pinned to Gnani. Live still needs the Gnani key for its speech output. The default remains `standard`; deploying this code does not automatically enable the paid robust profile.

Scribe's checked [pay-as-you-go price](https://elevenlabs.io/pricing/api) is $0.20/hour before taxes. The ledger uses that rate; override a contracted rate with `AI_PRICING_JSON={"elevenlabs":0.0033333333333333335}` (USD/minute). Keyterm surcharges are avoided. Actual account billing is authoritative. Separate channels submit the duration of each channel.

Optional RNNoise uses the FFmpeg-compatible `std.rnnn` from [arnndn-models](https://github.com/richardpl/arnndn-models) commit `0fda24c46d78f0207d820bb970fbe85c1971b39c`, SHA-256 `6b8943dc4a9b6b24425873992a44f29c0577503276456af46a8854774faeb294`. Provision the reviewed model separately; it is not committed with the app. A missing/invalid model falls back to original PCM. The `spectral` option uses FFmpeg's conservative 6 dB spectral denoiser. Both remain off by default because measurements showed regressions on some critical phrases.

## Reproduce the evaluation

Run from `backend` with dependencies installed and credentials in the environment. The generator uses four stock voices across the exploration and validation suites; it does not clone a person. Noise and speech are generated separately, mixed using active-speech RMS at +10/0/−5 dB, then filtered and encoded as G.711 μ-law at 8 kHz. SNR refers to the pre-codec mixture. Validation adds clipping, 100 ms packet gaps, digital silence and noise-only samples.

```sh
python -m scripts.generate_noise_corpus --output /path/to/private/corpus --generate
python -m scripts.evaluate_telephony /path/to/private/corpus/manifest.json \
  --output /path/to/private/corpus/comparison.json --transcribe \
  --profiles legacy raw spectral rnnoise scribe_v3

python -m scripts.generate_noise_corpus --output /path/to/private/validation --generate --validation
python -m scripts.evaluate_telephony /path/to/private/validation/manifest.json \
  --output /path/to/private/validation/comparison.json --transcribe \
  --profiles legacy raw robust scribe_v3
```

Without `--transcribe`, the evaluator scores manifest `reference`/`hypothesis` pairs offline. References and hypotheses are excluded from reports unless `--save-hypotheses` is explicitly used. That switch is useful for private error analysis. Synthetic audio is kept outside git. Reports include file hashes, conditions, provider profile, errors and latency; failures are counted and cause a nonzero exit.

WER is corpus-weighted Levenshtein distance after NFC/case/punctuation normalization. Indic combining marks are retained. Number rendering and cross-script transliterations are **not** collapsed, so strict WER can count equivalent spellings as errors. Critical-phrase recall separately checks manifest phrases, including negations. It is not a complete semantic safety metric. Repeated variants of one script are correlated; there is no claim of statistical significance across real callers.

Initial exploration: 29 generated clips, 791 reference words across variants; original path 38.18% WER, improved PCM 32.87%, spectral 32.36%, RNNoise 31.48%, direct Scribe v3 11.38%. RNNoise reduced aggregate errors but lost more critical phrases than raw PCM. Original temporary recordings were cleared during an environment transition; these initial figures are retained from the tool output. The subsequent validation uses new scripts, voices and noise and stores its artifacts persistently.

## Fresh validation results

New scripts and stock voices, new construction/office noise, plus clipping, packet loss, silence and noise-only inputs: 21 clips, 540 reference words across variants. The robust implementation was selected before generating this set. All 84 evaluations completed without provider errors.

| Path | Word errors / WER | Character error rate | Critical-phrase recall | p95 request-path time |
| --- | --- | --- | --- | --- |
| Original Gnani path | 148 / 27.41% | 24.31% | 57/90, 63.33% | 1.349 s |
| Improved standard PCM path | 153 / 28.33% | 24.67% | 58/90, 64.44% | 1.101 s |
| Integrated robust profile | 58 / 10.74% | 8.22% | 75/90, 83.33% | 1.829 s |
| Direct Scribe v3 baseline | 57 / 10.56% | 8.06% | 74/90, 82.22% | 1.367 s |

The robust profile reduced strict word errors by 60.81% against the original path on this set, and stayed within one word error of the direct frontier baseline. This is **Scribe integrated into Wilco**, not evidence of independently beating Scribe. PCM preparation alone did not improve aggregate WER on this fresh set. Differences also include request parameters, encoding, diarization and provider nondeterminism; do not attribute the whole change to any single filter.

All paths produced zero words on the three silence/noise-only samples. The harshest Hindi construction clip still had 89.29% WER with robust and 92.86% with direct Scribe. The result supports the explicit quality profile; it does not support guaranteed recognition under extreme noise. Timings are one local invocation per condition, include preparation/network/provider time, and exclude capture, Meet, synthesis and downstream actions. They are not production SLAs.

Machine-readable sanitized evidence: [telephony-validation.json](telephony-validation.json). Retained local corpus, generation receipts, references, hashes and private hypotheses: `/Users/vedantmoghe/Downloads/wilco-audio-evidence/validation`. Listening archive: `/Users/vedantmoghe/Downloads/wilco-audio-evidence/wilco-noisy-telephony-validation.zip`.

Final integrated backend suite: **585 passed** against disposable local Postgres. This includes PCM/G.711 handling, no dropped samples, stereo separation, quiet-speech retention, cancellation, denoiser fallback, provider requests, word timing, usage accounting, profile selection and existing bot/ingestion workflows. The broad run caught and fixed FastAPI form defaults in the bot's direct ingestion call. One unchanged agent-delivery timing test failed transiently on an intermediate run, passed its targeted rerun, and passed the final full run; the subsequently merged upstream change fixes that test’s delivery synchronization, and is preserved in the final 585-test run.

Real telephone recordings, natural accents/disfluency, live echo, overlapping human speakers, and downstream task/decision correctness remain separate acceptance work. Synthetic generation text is the reference and has not been independently transcribed by a human. Severe corruption can defeat even Scribe; do not present this as guaranteed recovery or global frontier superiority.

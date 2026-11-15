# Meeting response latency — 15 November 2026

The live meeting answer and task parser selected the default notes model, while the separate Live conversation feature already selected the configured fast model. Both meeting tools now explicitly use `gemini_fast_model`, retaining grounding, zero thinking, ledger attribution and worker deadlines.

The bot previously polled Meet chat before returning ordinary spoken commands, held its browser lock through chat panel retries, and queued result speech only after chat and its backend delivery acknowledgment succeeded. A disabled chat could suppress speech entirely.

Changes:
- Return settled spoken commands immediately; revisit typed chat on the next intake pass.
- Bound chat discovery to 500 ms and agent message delivery to two seconds, including lock acquisition.
- Queue completed/clarification speech before attempting chat delivery. Remember queued result IDs across failed chat/ack attempts to prevent repeated speech.
- Fill the chat input in one operation, replacing unfinished drafts before retries.

Validation: 540 backend tests passed against a new disposable local Postgres instance (including six new regressions). Chromium checks for textarea and contenteditable inputs confirmed multiline replacement and one submission. No real meeting or account connector mutation was used in these checks. Existing Qdrant compatibility warning remains unrelated.

These checks establish the scheduling behavior, not an acoustic latency improvement or percentile. Model latency, caption stabilization, TTS, network and Meet playback still contribute. The prior synthetic voice probe's 4.3-second result is not a before/after measurement for this release. Real-call verification should measure end of question to first audible response, plus board completion separately.

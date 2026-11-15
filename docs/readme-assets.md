# README assets and claim checks

## UI gallery

`docs/screenshots/readme/{home,tasks,memory}.png` are unedited browser screenshots of the ink-and-yellow redesign at UI commit `eaa6f21` on `codex/engagement-software-demo`, captured on 15 November 2026 at 1440 × 1000. Source was exported into an isolated preview with its own installed dependencies. No contributor application files were modified.

The preview used authenticated, read-only API requests to a synthetic demonstration workspace. The demo account token is kept outside Git. These are implementation-preview screenshots, not generated concepts and not a claim that this UI commit is already deployed. The data is synthetic. Replace these files after the next accepted UI release to keep the README current.

## Speech credit

The local demo production assets include `audio-script.json`, `audio-receipts.json`, and Prisma/Memory evidence. They specify Timbre v2.5 (English/Hinglish), Timbre v3.0 (Tamil/Marathi), and separately generated ElevenLabs music. The README credits generated speech to Gnani and does not claim that music or reasoning comes from Gnani. No key, private session file, raw recording, or local export is committed here. The final video URL is intentionally pending (`DEMO_VIDEO_URL` in README.md).

## Editorial sources

- README guidance: [Crafting Effective READMEs by softaworks](https://github.com/softaworks/agent-toolkit/tree/main/skills/crafting-effective-readmes), installed locally and read for this task.
- Award descriptions: copied verbatim from the user-provided brief; cross-checked against [Gnani’s programme page](https://www.gnani.ai/internship). Award fit is a positioning judgment, not an award result or eligibility determination.
- Product scope: source at `0412ada`, especially the transcription/TTS/voice-clone services, voice-workflow notes, action-agent design, and meeting-first FigJam acceptance limits.
- Setup: retained from the main-branch README in [development.md](development.md), with Gnani speech attribution and deployment timing wording corrected.

No customer traction, retention lift, measured language parity, noisy-telephony advantage or live FigJam acceptance is claimed. Backend test counts refer to the recorded voice-workflow checkpoint; no backend tests were rerun for this documentation-only change.

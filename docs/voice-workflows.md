# Voice workflows

Implemented from main `d184828` on `codex/voice-workflows-20261115`. No database migration or new package is needed. Deployed to production on 15 November 2026 as application commit `694f15285010a41b99566b280d921db911c9601d` through PR #15.

## Try the features

| Feature | Entry point | Result |
| --- | --- | --- |
| Voice to Jira | Talk to Wilco: “Create a Jira ticket: fix the webhook retry bug, assign Vedant” | Creates a Wilco task and sends it through the existing Jira integration; speaks the returned key and displays its link. Assignment is confirmed only when Jira accepted an assignee. |
| Spoken stand-up | Home → Missed stand-up? → Catch me up; also the existing per-person stand-up panel | Reads the latest accessible stand-up's updates, blockers and plans with Timbre. Choose English, Hinglish or another supported language. The occurrence's actual date is retained; old plans are not described as today's plans. |
| Running translations | In call: “Wilco, translate to Tamil” | Posts a labelled Tamil summary in shared meeting chat about every 30 seconds when new settled captions exist. Up to three languages concurrently. “Wilco, stop translations” clears them. |
| Who said that? | Delivery Radar → a recent decision → Who said that? → Hear original quote | Shows the current speaker label, timestamp, original transcript line and any corrected wording; plays a clip from the recording, capped at 45 seconds. |
| Pre-meeting voice brief | Home → Listen to your brief | Reads the existing calendar brief and open tasks. Existing calendar scheduling prepares briefs ten minutes before calls; Home checks for ready briefs every minute. |

## Boundaries and recovery

Jira writes use the authenticated Talk to Wilco account and existing organization Jira connection/project/person mapping. Shared-call speaker labels are not an authentication mechanism. An in-call Jira creation request directs the person to signed-in `/live`; the bot does not borrow the recorder's authority. Normal in-call action items and existing two-way Jira sync remain available.

Voice requests are deduplicated by user and audio fingerprint under a Postgres advisory lock. The same reserved connection holds that lock across task/Jira helper commits, and cleanup releases or invalidates it. A marker is committed before the Jira POST. An ambiguous failure leaves the task in Wilco and tells the person to inspect Jira before manually sending again; replaying the same audio does not retry that POST. Failed task extraction requires task review before Jira creation. The existing Jira integration may create an issue without an assignee when the project rejects optional fields; Wilco reports that assignment could not be confirmed.

Running summaries reuse the bot's existing live Meet/Teams captions. This checkout does not have a continuous Prisma transcription stream; Prisma remains the recorded-meeting and Talk to Wilco transcription path. There is no added periodic STT call. Translations use the fast Gemini wrapper with `feature=live_translation`, attributed to the recorder and meeting in the usage ledger. Requests are bounded to 60 recent caption chunks, three languages per call and twelve translation requests per minute per capture. They do not speak over the call. Chat is public to the call, not a private per-person caption channel. Recording pause suppresses translation and private caption intervals remain excluded. Stop/unsubscribe suppresses in-flight translation delivery. Subscriptions last for the bot visit.

Decision sources must be verified evidence that still resolves to a matching segment within the same readable meeting. Stale and cross-meeting citations never yield an audio URL. Playback rechecks access and evidence before extracting from the meeting's latest processed recording with FFmpeg. Missing evidence, timestamps, recording files or FFmpeg produce an explicit unavailable state. Original ASR words and corrected words are distinguished; speaker names retain the product's existing verification limits. Imported timestamps must correspond to the attached recording to identify the intended passage.

The players generate speech only after a tap, reuse the existing translation/Timbre caches, and retain translated text if speech is unavailable. Stopping, changing language, changing text or leaving the player invalidates pending playback. Home catch-up and ready-brief reads do not call an AI provider.

## Verification

- Full backend suite: **558 passed** against disposable local Postgres, with provider and Jira calls mocked. One existing Qdrant availability warning.
- Thirteen new tests cover negated requests, real receipt propagation, retry/concurrency handling, ambiguous Jira failure, extraction fallback, shared-call authority, dated/private stand-ups, cross-meeting/stale evidence, actual FFmpeg extraction from synthetic audio, incremental/bounded/cancellable translations, pause, bot authentication and billed model selection.
- Frontend production build and TypeScript passed.
- Nine browser checks passed with synthetic API data: ready brief, pending-audio cancellation, Hinglish text/playback, narrow Home layout, source speaker/time, audio controls, narrow Delivery layout, playback removal on close and desktop Delivery layout.

These checks do not validate real Jira assignments, Prisma/Timbre speech quality, real-call chat delivery, translation accuracy or acoustic latency. Real service/call acceptance remains required after deployment. No Jira issue, real meeting recording or external chat message was created during verification.


## Pre-release correction

A focused local-sequential Bug Hunter review covered voice task dispatch, task intent, running translations and the Live route (four source files, two confirmed issues, none dismissed). Both issues were reproduced before fixing: merely mentioning Jira inside an internal task could trigger an external issue, and one failing translation language could starve later subscribers. Jira dispatch now requires an explicit Jira ticket/issue/task creation destination; each translation language handles its own ordinary provider/delivery failure while cancellation still propagates. “Issue” creation requests are recognized alongside tickets.

After correction: 560 backend tests passed, including two new reproductions; frontend production build/typecheck, extension checks and five native FigJam checks passed. The release probe now checks signed-in stand-up and decision-source routes, invalid credentials, synthetic cleanup and (in model-canary mode) the real translation endpoint. Its authenticated local HTTP run passed without provider calls. Production verification passed as recorded below.


## Production release verified

[PR #15](https://github.com/testing-archit/bhadra/pull/15) merged, and [workflow 43709991315](https://github.com/testing-archit/bhadra/actions/runs/43709991315) passed tests, image builds, idle-aware rollout and live verification. Rollback images were preserved before replacing backend, frontend and notetaker. The new backend/notetaker image identities matched their release tags; runtime imports, Google auth state and isolated microphone checks passed.

The live probe passed authenticated stand-up/decision-source reads, invalid-credential rejection, real synthetic Tamil translation, durable agent/board execution, acknowledgment and synthetic-record cleanup. Its synthetic voice path passed Prisma transcription → fast Gemini reply → Timbre/Shlok speech (4,091.31 ms server-side for the one observed probe, excluding its cached input TTS, client/WAN/Meet playback and acoustic latency). No real Jira issue, email or meeting was created by verification.

Final independent public requests returned 200 for `/health`, `/`, `/delivery` and `/live`, and 401 for invalid credentials on `/api/tts/standup`. Real human call delivery, spoken names/assignments and translation quality still require in-call acceptance; the existing signed-in Jira and live-caption boundaries above are unchanged.

# Team coordination

Updated 15 November 2026. Read this before editing or synchronizing this checkout.

## Ownership

- Codex owns the reference-video UI and UX redesign, as assigned by the latest user instruction. The prior frontend was preserved in commit `50dd6cf` before edits. Other sessions should wait for the current UI handoff before editing those surfaces.
- Codex owns this coordination handoff and integration checks. Backend or extension changes need an announced scope before work starts.
- The other contributor's current scope is unknown. Treat existing changes as work in progress until their owner identifies a completed checkpoint.
- Each contributor should append a dated handoff with their files, commit, checks, and remaining work. Reading this file is coordination; it does not imply another running session has acknowledged it.

## Git workflow

- The user's message requested both regular pulls and no pulls. Clarification is pending. Until resolved, fetch and inspect remote updates; do not pull or merge into the shared working tree.
- The shared checkout has substantial uncommitted changes, including a product rename and UI redesign. Preserve its index and files. Never stash, reset, switch branches, or stage everything here while another session is editing.
- Use a separate worktree or clone and a topic branch for integration. Confirm the base shares the current repository history before merging. Review overlaps with the owner, resolve deliberately, and run relevant checks before publishing.
- Aim to push reviewed, completed commits about every ten minutes during active work. Skip a checkpoint when nothing is ready. Do not create empty commits or commit another contributor's unfinished files to satisfy the timer.
- Push topic branches normally, with an explicit remote and branch. Never force-push. A rejected push means inspect the remote and reconcile in isolation; do not retry with force.
- Pushes to `main` trigger production deployment. Checkpoint pushes belong on topic branches; integrate into `main` only after checks and coordination.
- Do not include credentials, recordings, exported session logs, or local scratch files in checkpoint commits.
- No unattended commit/push loop has been installed. The ten-minute target applies while an agent is actively working; it does not continue after a session ends.

## Previous session handoff

Source: the locally supplied session export. That session reports commit `10385b4` was pushed and deployed, with 396 backend tests and a frontend build passing. It added the focused Home briefing, guided task/decision/speaker review, consent-based voice enrollment, and conservative speaker matching. Meeting transcription retained the contributor's short Prisma REST clips after the Batch API test remained queued.

Still pending from that session: a real Google Meet with two enrolled employees to assess speaker matching on actual voices. Do not treat synthetic voice checks as that acceptance test.

## Codex handoff on 15 November 2026

- Fetched `origin`; `HEAD` and `origin/main` both point to `10385b4`, with no commits ahead or behind at inspection.
- Extension validation and Sheets export checks passed (`npm test`). Frontend TypeScript checks passed (`npm run typecheck`). These checks do not validate the entire unfinished rename or UI in a browser.
- Found the local Claude session for this project. Its latest visible messages concern fonts, stale stylesheets, and an isolated frontend preview on port 3100. No live session messaging channel is available, and Claude has not acknowledged this handoff.
- Codex changed only coordination documentation and the pointers in the agent guides. Existing application edits and staged asset renames belong to the prior work and remain untouched.

## Design skill setup

The user subsequently requested relevant design skills from the supplied catalog. Codex installed `frontend-design`, `shadcn`, and `ui-ux-pro-max` into `.agents/skills/`, with Claude links and a setup guide in [design-skills.md](design-skills.md). Existing UI and animation work remains with Claude. Read the setup guide before applying the skills; keep `DESIGN.md` and the existing components as the project defaults.

## Current UI handoff

The user's latest instruction assigns the UI and UX redesign to Codex using the supplied local reference video. This supersedes the earlier UI ownership assignment. Codex is working in `/private/tmp/bhadra-reference-ui` on `codex/reference-ui-20261115`, preserving a snapshot of the existing frontend first. Other sessions should avoid editing Home, the shell, global theme styles, the notetaker dialog, and guided review until handoff. No other session has acknowledged this note.

Four additional catalog skills are installed and linked: `improve-ui`, `fixing-accessibility`, `fixing-motion-performance`, and `ux-writing`. The broader application changes in the shared checkout remain uncommitted; checkpoint branches do not deploy them.


## Reference redesign implementation

Codex reworked Home, the shared shell, the capture dialog, and guided meeting review on `codex/reference-ui-20261115`. The new interface uses a static cool atmosphere on Home, a compact composer, a focused follow-up, five primary destinations, and progressive disclosure for detailed meeting content. Capture consent remains mandatory; voice learning has a separate opt-in. `DESIGN.md` describes the current direction.

Preview runs from the isolated worktree on `http://localhost:3200`. A temporary loopback proxy on port 3300 forwards to the existing local backend on 8000, because backend CORS does not allow 3200. The proxy and preview env file are local-only. UI checks use saved demo reads and intercept mutations, so verification does not send a bot into a real meeting or change saved notes.


## Latest image reference revision

The user rejected the dark hero and supplied a light/violet mobile meeting-app image. That image now governs the UI direction. Codex replaced the hero with the capture/shortcut tiles, shared meeting cards, a working calendar agenda, and mobile bottom navigation on the existing UI branch. The light theme is now the default; explicit saved theme choices are retained. Existing recording consent, guided review, and access rules remain in place. `DESIGN.md` reflects this revision.


## Production release request

The user authorised deployment of the light/violet UI. Preflight found production and `origin/main` at `10385b4`, with a clean VM checkout and healthy services. The release changes only frontend application files; backend, notetaker, compose, and deployment workflow changes in the shared checkout are excluded. A frontend image rollback tag, `charcha-frontend:pre-violet-ui-20261115`, preserves the previous release. The UI accepts both the existing and renamed Jira project-response fields so the backend can remain on its current contract. Deployment and live verification are tracked by the repository's Test and deploy workflow.

## Task focus deck, 15 November 2026

The user selected Focus deck and Done / Snooze / Reassign from the design options. Codex is updating only Tasks and a dedicated task-focus component in `/private/tmp/bhadra-reference-ui`. The isolated branch fast-forwarded to `a62644a`, retaining the collaborator's meeting whiteboards and bot chat fix. Keep the shared checkout and its unfinished backend/extension changes intact. This pass removes repeated task summaries, puts filters behind a control, and preserves list/board and existing task APIs.

Task focus deck implementation is ready for review: Tasks page, `task-focus-deck.tsx`, and scoped CSS only. The existing List/Board, exports, bulk tools, and task editor are preserved behind compact controls. Frontend build/typecheck and the local browser walkthrough passed; task mutations were mocked. Screenshots and validation limits are recorded in `docs/task-focus.md`. ESLint is blocked by the existing TypeScript 7 / typescript-eslint incompatibility. Shared frontend copies contain this Tasks change; other shared working-tree changes remain uncommitted.

## Task workspace revision, 15 November 2026

The user rejected the deployed single-card deck as too empty. Codex is replacing that default with a compact queue and selected-task work area, with inline expansion on mobile. Keep Done / Snooze / Reassign and Undo, but restore multiple tasks to the overview. Work remains isolated in `/private/tmp/bhadra-reference-ui`; Tasks and its dedicated component are the edit scope. Production at `25559c0` is the previous deck until the revised UI is verified. The shared meeting-agent planning handoff remains intact.

The user subsequently chose option C: compact task cards. That is the implemented direction, superseding the queue/inspector exploration above. Tasks now displays several cards, with in-place source/actions, completion, Undo and an actual Waiting on strip. The new component is `task-workspace.tsx`; `task-focus-deck.tsx` is removed. Build/typecheck and the browser checks are recorded in `docs/task-cards.md`, with four preview screenshots. This checkpoint is for visual feedback on the topic branch; the production main branch retains `25559c0`.

## Mascot-led frontend, 15 November 2026

The user approved the first generated mascot and requested matching site colours plus real implementation, supported by image-model UI references. Codex owns global frontend theme, brand assets, shell, Home welcome area and the connected Tasks surface in `/private/tmp/bhadra-reference-ui`. Existing backend/board/pipeline work remains with its isolated owner. Use the approved mascot, warm paper canvas, pastel face colours, teal selections and orange key actions. Preserve actual task data, access rules, consent, List/Board links and reversible task mutations. No bulk changes to the shared checkout.

The mascot-led first pass changes shared frontend tokens, the approved PNG brand assets, the existing Home welcome area/sidebar, and the connected Tasks Flow. Base UI menu grouping is exposed for task actions. TypeScript/build, palette contrast checks and the local browser walkthrough are recorded in `docs/mascot-workspace.md`; task writes are mocked. Model-generated reference images and exact prompts are in `docs/design-references/`. Keep the backend/action-agent work isolated and intact. This first pass is a UI-branch preview, not a production deployment.

## Useful density and return value, 15 November 2026

The user requested a behavioural-design pass to reduce empty space and improve reasons to return. Codex is revising Home in `/private/tmp/bhadra-reference-ui`: visible follow-ups and actual progress, latest-meeting review, compact schedule/connection states, quick memory questions, and compact recent notes. Claims about retention are hypotheses; preserve honest counts, user control, real data and existing consent. No tracking vendor, automatic AI generation, extra backend work or production deployment is included. The mascot-led theme and Tasks Flow remain intact.

The Home implementation is verified with a production build and 20 browser checks using demo meeting snapshots and synthetic tasks; writes and memory answers are intercepted. Screenshots and the behavioural rationale are in `docs/home-follow-through.md`. Shared copies were synchronized only after checking the baseline; existing stylesheet and backend changes were preserved. The next checkpoint integrates fetched main into this isolated branch, with no production release.

## Meeting agent planning, 15 November 2026

- Added `docs/meeting-agent-plan.md` at the user's request: voice commands, whiteboard operations, Jira/email execution, personalized preparation, latency measurements, scaling, and phased acceptance criteria.
- Documentation only; no application changes, implementation runs, commits, or deployment in this planning task. Existing shared changes and `docs/claude-meetings.md` remain intact.
- Checked the plan's local references, section coverage, and fenced blocks. Performance targets are proposals; code-derived delay estimates are not production measurements.
- Next work starts with baseline reconciliation and instrumentation. Reuse the newer worktree's existing boards rather than rebuilding them from the older shared checkout.

## Meeting pipeline implementation scope, 15 November 2026

Codex is implementing command scheduling and metadata-only stage timings in `/private/tmp/bhadra-meeting-agent`, branch `codex/meeting-agent-pipeline`, based on fetched `origin/main` at `25559c0`. Scope is bot runtime, focused regression tests, and planning handoff. Existing board/UI behavior and shared unfinished application changes are preserved. No production deployment is included in this checkpoint.

### Command runtime checkpoint

Implemented on `codex/meeting-agent-pipeline` from `25559c0`: bot command runtime, caption wakeups, bounded execution/playback, metadata-only timings, optional MLflow dependencies/export, shutdown playback cleanup, focused tests, and tracing validator. Validation: 17 focused tests passed; four synthetic traces stored/retrieved; compile and whitespace checks passed. Full suite, production confirmation, and real-call acceptance remain pending. No deployment. See `docs/meeting-agent-plan.md` implementation log and the bot README for scope and commands.

## Voice whiteboard checkpoint, 15 November 2026

Continued on `codex/meeting-agent-pipeline`: structured board operations and bot-only endpoints, replay-safe revisions/undo, optimistic concurrency without provider calls under row locks, Wilco/legacy command routing, and opt-in canvas presentation assets. Presentation defaults off and is Meet-only. Full backend suite: 434 passed against disposable local Postgres. Local Chromium/WebRTC proof and synthetic screenshot passed; real Meet remote reception, live model/audio accuracy, and capacity remain unverified. See `docs/voice-whiteboard.md`. No deployment.

## Meeting action agent scope, 15 November 2026

Codex continues in `/private/tmp/bhadra-meeting-agent` on `codex/meeting-agent-pipeline`: durable command jobs, bounded workers and context, task/tool execution with commit fencing, job status/cancellation, and bot interruption/progress handling. Existing board/presenter features are retained. This scope does not deploy production or enable personal-account Jira/email writes from unauthenticated speaker names.

## Durable meeting action agent checkpoint

Implemented in `/private/tmp/bhadra-meeting-agent` on `codex/meeting-agent-pipeline`: durable Postgres jobs and typed tools, bounded multi-step planning, atomic tool receipts, replay handling, leases/recovery, deadlines/cancellation fencing, cancellation-before-submit records, persistent async bot transport, status delivery, and priority interruption/cancel controls. Model context, thinking, attempts, timeouts, and provider thread count are bounded. Current tools are current-call board operations, internal action items, grounded answers/drafts, and clarification; account-specific connector writes remain outside this shared-call executor.

Validation: full backend suite 456 passed, plus focused checks after action-routing hardening. Native MLflow: two stored/retrievable run/plan/tool traces. Local ASGI/Postgres load check: 20 requests / five sessions / two workers with 100 ms simulated inference; acknowledgment p95 776 ms, completion p95 2,110 ms. No actual model/audio/Meet latency claim. See `docs/meeting-action-agent.md` and `docs/agent-queue-benchmark.json`. Backend/schema must be updated before the bot. Presentation remains off by default; no deployment. Shared application changes remain untouched.

Final verification: 456 backend tests passed in 13.02 seconds; compile/whitespace checks passed. The final local 20-request/five-session simulated-inference check measured acknowledgment p95 398 ms and completion p95 1,863 ms with peak parallel inference 2. Earlier measurements remain in the benchmark artifact; these are not production or acoustic latency guarantees.

## Agent deployment authorization, 15 November 2026

The user explicitly requested pushing, merging and deploying the action-agent branch, and will perform real-call acceptance afterward. Codex is releasing only `codex/meeting-agent-pipeline`; the mascot/frontend preview is not included. Release preparation adds PR-only checks, rollback image/environment snapshots, and authenticated live agent/notetaker smoke checks. Presentation will be enabled once on the server for this authorized test; subsequent deploys preserve the server's setting. Deployment remains pending until CI and live verification pass.

## UI integration checkpoint, 15 November 2026

Home follow-through commit `4a89183` integrates main at `ee8a3ed` in the isolated UI branch. The only merge conflict was concurrent appended handoffs in this document; both were retained. Incoming backend/action-agent and deployment files have no frontend source overlap. This checkpoint retains the reviewed mascot theme, Tasks Flow and Home changes and does not push to production main.

## Memory simplification scope, 15 November 2026

Codex is streamlining Memory in the isolated UI worktree: one composer, compact recent meeting entry points, on-demand history and a draft/apply meeting picker. Preserve existing cited answers, voice input, conversation history, selected meeting boundaries and URL question handoff. Only Memory and scoped styles are owned by this pass; no backend or production deployment.

Memory implementation is complete: production build/TypeScript and 11 local browser scenarios passed with mocked chat/deletion requests. Actual desktop/mobile/light/dark and conversation screenshots are in `docs/screenshots/wilco-memory-*`; details in `docs/memory-workspace.md`. Shared copies were synchronized after checking baselines and applying only scoped CSS.

## Deployment verification fix

PR #1 merged at `ee8a3ed`; backend and notetaker images restarted. The first deployment run's final probe failed with a connection error while the API was starting. Public health and new authenticated route checks succeeded afterward. Codex is fixing readiness polling and SSH-script stdin consumption, and preserving initial rollback snapshots on retries. Deployment will only be reported complete after the live model-backed canary and bot runtime checks pass.

## Talking mascot release scope

The user explicitly requested an animated talking mascot for Live and a push/production deployment for testing. Codex owns Live, its SVG mascot and scoped styling, plus necessary session cleanup fixes. Release includes the already reviewed mascot theme, Home, Tasks Flow and Memory on this branch. Preserve collaborator backend changes by integrating latest main in isolation; use the existing checked deployment workflow.

## Live provider compatibility fix

PR #2 merged at `737d10d`; services are healthy and presentation is enabled for the authorized test. The real model canary exposed an SDK serialization error: strict nested Pydantic fields became `additional_properties` in the legacy response schema. A synthetic production probe confirmed that sending JSON Schema directly succeeds with one whiteboard operation. Codex is correcting the shared generation wrapper, preserving strict local validation and cost attribution, and adding a real SDK transport regression test. A manually invoked diagnostics mode checks service metadata and makes a synthetic provider request without joining a meeting; it never logs keys or real meeting content. Release verification remains pending.

## Agent production release complete, 15 November 2026

PR #3 merged; application commit `25fec901b995ded0a540f3bd922758a92b01432f` deployed successfully in workflow `43661300614`. All 457 backend tests passed in CI. The real model-backed command/job/board canary succeeded, including delivery acknowledgment and synthetic cleanup (admission 33.69 ms; completion 2,904.18 ms, container-local HTTP, excluding audio/Meet/WAN). Backend and notetaker images match their release tags, runtime imports/auth state checks passed, and server presentation is enabled for the authorized test. Public app/health are 200; protected command API is 401 without credentials. Original rollback snapshots remain available. Real-call voice/remote-presentation acceptance is now with the user. The unrelated mascot/frontend/shared application work was not included. Release evidence and limitations are in `docs/meeting-action-agent.md`.

## Meeting voice reliability and FigJam scope, 15 November 2026

Following the user's real-call feedback, Codex owns command recognition/drawing failures, voice latency, audio feedback diagnostics/fixes, and a shared FigJam integration in `/private/tmp/bhadra-meeting-agent`. The user selected FigJam/Figma. Keep bot camera assets/generator with the mascot owner. Existing unfinished shared changes remain untouched. Production diagnostic reads must redact credentials and avoid logging real transcript/audio content. Prior release authorization persists for verified fixes; do not claim live FigJam access until an account/file is connected.

## Meet camera mascot correction

The user reported the old Charcha camera card still visible in Google Meet. Codex owns only the bot camera asset generator, generated idle/speaking cards and their source mascot. Replace the legacy artwork with the approved mascot and Wilco label, retaining camera capture and speech switching. Deploy through the existing idle-aware bot release; do not interrupt an active recording.

Meet camera replacement uses the exact approved mascot source PNG and browser-rendered 16:9 cards. The existing 640×360 canvas stream was verified in Chromium, including live video tracks and alternating speaking indicators. Generator uses the existing Playwright dependency; runtime continues loading checked-in PNG frames. Recording/session logic is unchanged.

## Voice reliability and FigJam production handoff

The user reported missed drawing, slow speech and noise, then selected FigJam. PRs #6–#8 are merged; application commit `eaa87deeae0e52857b4b19b915d9ec7cc27cb642` deployed successfully in workflow `43670622648`. The approved Meet mascot changes were integrated and preserved. Shared unfinished application files were not staged or overwritten.

Implemented full drawing-instruction routing, repeated caption wake words, shorter settling/chat waits, fast-model compatibility, prioritized/bounded live STT, batched/parallel context reads, URL-free short speech, English Gnani voice selection, isolated browser microphone playback, and explicit Live interruption with echo gating. Added a recorder-paired native FigJam bridge with scoped hashed tokens, durable delivery/acknowledgment, conflict guards and an installable development-plugin template/configuration helper. New bot requests select FigJam; finished meetings retain its shared URL. Only the plugin host needs installation; real Figma pairing and remote Meet sharing still need user acceptance.

Verification: 471 backend tests in CI; five native operation checks; frontend build/typecheck; browser setup/mobile/echo/interruption walkthrough; real Chromium/WebRTC audio isolation/cancellation; native MLflow routing evaluation 10/10. Real provider canaries: board completion 1,668.18 ms; STT 1,404.05 ms; fast reply 995.50 ms; Gnani Timbre/Shlok 1,872.96 ms; voice pipeline 4,272.51 ms. These are single server-side observations, excluding real-call/client timings. Bot/runtime imports and image identity checks passed. Public health/download were 200; invalid API credentials were 401. See `docs/voice-figjam-reliability.md` for setup, evidence, archive checksum and limits. No real call, Figma account write, Jira/email mutation or source change outside this scoped branch was used for validation.

## Meeting-first FigJam execution correction

The user rejected per-meeting portal connection/plugin pairing and reported a read-only refusal for a FigJam command. Codex owns spoken alias/action routing, direct browser execution of FigJam open/create/draw commands, and one-time reusable Figma authorization. Work continues in `/private/tmp/bhadra-meeting-agent` from main `3fae71d`; preserve all newer khata, Live, branding and camera changes. Do not claim a native file was created without a verified Figma URL/tool receipt. No per-meeting portal pairing is the intended default.

This correction also owns the live meeting board page and a small FigJam file-link component: replace the default pairing/built-in-draft surface with the resulting native URL. Existing unrelated Live, khata, branding and camera work is preserved. Implementation and limits are in `docs/meeting-first-figjam.md`. A local Figma sign-in window is awaiting the account holder; no credentials have been saved or provisioned. Native UI drawing and remote Meet acceptance remain pending that sign-in.

Checkpoint verification: 534 backend tests pass against disposable local Postgres; frontend production build/typecheck pass; native MLflow routing evaluation passes 15/15; real Chromium verifies synthetic canvas-only frame transfer and login suppression. No actual Figma write or new call-latency result has been verified. Account sign-in remains the live acceptance dependency. The bot Dockerfile includes the new executor and checks its import at image build.

## Software-team UI refresh, 15 November 2026

The user requested a more expressive interface across all pages and replaced the retail Voice khata page with Delivery Radar. Codex built this on isolated branch `codex/ui-refresh-20261115` in `/Users/archit/Desktop/charcha-ui-refresh-20261115`; the shared checkout remains untouched. Work was divided across core work pages, meeting intelligence pages, support pages, and public utility pages. `/delivery` uses existing accessible task, decision, and project APIs, while `/khata` redirects there. Legacy khata API routes remain for existing integrations. Scoped styles add responsive signal graphics and reduced-motion fallbacks. The branch includes the latest `origin/main` FigJam work via merge `8e53521`, preserving its native board changes. Frontend production build/typecheck and desktop/mobile browser renders pass. This topic branch has not been merged into `main` or deployed.


## Meeting response latency scope, 15 November 2026

Codex owns a focused latency fix in `/private/tmp/wilco-meeting-latency` on `codex/meeting-latency-20261115`, based on fetched main `5e62c81`. Scope: live answer/task model selection, bot caption intake and independent speech/chat delivery, plus regression checks. Preserve incoming native FigJam, camera and frontend work. No active meeting is restarted for validation.

Latency fix verified: 540 backend tests passed with disposable Postgres; Chromium multiline/retry checks passed for both supported chat input types. Changes explicitly select the fast meeting model, prioritize spoken intake, bound chat browser-lock occupancy, and queue speech independently of chat/delivery acknowledgments with retry deduplication. Details and live-measurement limits: `docs/meeting-response-latency.md`. Release uses prior voice reliability deployment authorization and the idle-aware notetaker update.

## Meet-visible whiteboard scope, 15 November 2026

Codex owns automatic board presentation and the camera-tile fallback in `/private/tmp/wilco-meet-board` from fetched main `48827ef`. Scope: bot presenter/renderer, camera canvas integration and focused checks. Keep native FigJam authorization and canvas-only capture boundaries, preserve the approved mascot outside board mode, and retain voice latency fixes. User requested visible in-Meet whiteboards; release through idle-aware deployment. Native Figma sign-in remains a separate dependency.

Meet board implementation verified: 545 backend tests pass; Chromium outgoing-camera pixel checks confirm live canvas updates and mascot restoration; native frame/login suppression check passes. Local two-peer ICE negotiation did not complete, so remote Meet reception remains an acceptance check. All board edit requests now request display; sharing failures use the existing bot video track, and camera fallback stays live across updates. Native FigJam still requires its missing one-time sign-in. See `docs/meet-visible-whiteboard.md`.


## Claude engagement pass and software-company demo, 15 November 2026

The user requests exact implementation of the Claude canvas and section 3b of docs/design/redesign-spec.md, plus rich synthetic software-team data published to the demo. Codex owns Landing, Home, Meeting, Tasks, Memory, shared tokens/shell where required by that spec, and the demo seed/validation in /private/tmp/bhadra-engagement on codex/engagement-software-demo from d184828. Preserve newer bot latency, native FigJam, camera and delivery work. Keep the dirty shared checkout untouched apart from appended coordination. Canvas access is currently blocked by Cloudflare; local source/artboard path has been requested while independent spec/data work proceeds. No canvas click-through or exact visual match is claimed until the reference can be inspected.
## Voice workflow scope, 15 November 2026

Codex is implementing the requested voice-to-Jira, spoken stand-up/brief, running call translations, and decision quote playback in `/private/tmp/wilco-voice-workflows`, branch `codex/voice-workflows-20261115`, from main `d184828`. Reuse existing Jira sync, Timbre, transcript evidence and calendar briefs. Shared-call commands must not impersonate an authenticated user. Provider and external writes are mocked during verification; no deployment is included in this request.

Voice workflow implementation is ready on `codex/voice-workflows-20261115`: authenticated Talk to Wilco → Jira, spoken stand-up and ready-calendar-brief players, running shared-chat translations, and verified original decision quote playback. Full backend suite: 558 passed; frontend build/typecheck and nine synthetic browser checks passed. In-call Jira commands direct users to signed-in Live; translation uses existing live captions (there is no continuous Prisma stream in this checkout). Real provider/Meet/Jira acceptance and deployment remain pending. See `docs/voice-workflows.md` for files, behavior, cost bounds and limitations. Shared application sources remain untouched.

## Voice workflows release, 15 November 2026

The user now authorizes fixing and deploying all five voice-workflow changes. Codex is reviewing and releasing `codex/voice-workflows-20261115` in its isolated worktree, preserving main's existing UI/whiteboard/latency changes. The separate engagement redesign branch has an in-progress owner and is not part of the five-feature checkpoint. Release will run PR checks, preserve rollback images, wait for idle services, and verify deployed routes/runtime/provider canaries.

Pre-release correction confirmed and fixed unintended Jira dispatch from an internal task mentioning Jira and starvation of later translation languages after one failed. Full suite passed 560 tests; frontend build/typecheck, extension and FigJam checks passed. The authenticated local HTTP release probe passed. Production probe now covers the new read routes and synthetic translation, retaining existing model/voice canaries and cleanup.

## Voice workflows deployed, 15 November 2026

PR #15 merged at `694f15285010a41b99566b280d921db911c9601d`; workflow `43709991315` succeeded. All five voice-workflow changes plus the two pre-release corrections are live. CI passed 560 backend tests and applicable frontend/extension/FigJam checks; the production build, rollback snapshots, idle-aware service restarts, image identity/runtime checks, authenticated stand-up/decision-source reads, real synthetic translation and Prisma/Gemini/Timbre canary passed. Public health/Home/Delivery/Live return 200; invalid credentials on the new stand-up endpoint return 401. Synthetic records were removed. No actual Jira ticket or real meeting was created by verification. Real in-call quality acceptance remains with the user; scope and evidence are in `docs/voice-workflows.md`.


## Engagement final release integration, 15 November 2026

The user authorizes final deployment. The temporary engagement worktree was no longer present, so Codex recovered its pushed commits into /Users/vedantmoghe/Downloads/bhadra-engagement-release. Merge main 0412ada deliberately: preserve Home spoken stand-up/ready briefs and Listen playback generation guards alongside compact debrief controls. Shared unfinished files remain untouched. CI and production verification must complete before claiming deployment.

Release build caught a Next/Turbopack Google-font query failure for Doto. Bundle the same upstream Google Fonts Doto variable font with its OFL license through next/font/local, preserving the design and avoiding the failing remote font transformation. No runtime font CDN dependency is introduced.
## README pitch release scope

Codex is preparing a documentation-only product pitch in `/Users/vedantmoghe/Downloads/bhadra-readme-release` on `codex/readme-release-20261115`. The earlier temporary worktree is no longer available. Scope: README, preserved development guide, source/capture notes and three unedited screenshots of UI commit `eaa6f21`. The demo video link is pending; Gnani speech and separate music credits are explicit. Shared application changes remain untouched.

README pitch validated: local image/link checks and Markdown fences pass; GitHub Markdown API render loads all images. Three screenshots were visually inspected after loading finished. Preserved operational setup in `docs/development.md`. No application source, private tokens or recordings are included. The selected award wording comes from the user’s supplied brief; no award wins, unmeasured accuracy or customer adoption is claimed.

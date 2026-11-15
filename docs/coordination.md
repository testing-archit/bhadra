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

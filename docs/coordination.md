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

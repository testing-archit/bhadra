# Team coordination

Updated 15 November 2026. Read this before editing or synchronizing this checkout.

## Ownership

- Claude owns the ongoing UI generation, frontend styling, fonts, brand components, and dashboard work. Codex will inspect these files without editing them until a handoff.
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

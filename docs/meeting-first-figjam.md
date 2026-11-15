# Meeting-first FigJam execution

15 November 2026. Supersedes portal pairing as the default meeting flow.

## Intended experience

Say “Wilco, open FigJam.” The notetaker opens `https://figjam.new` in its own signed-in browser, verifies the resulting native board URL and canvas, returns the file link, and attempts canvas-only Meet presentation when enabled. Subsequent requests use the same board for this capture. The Live page shows its link without a pairing form or built-in board.

One reusable **bot Figma account session** is required. This is distinct from connecting a board for each meeting. Figma owns file permissions: returning a URL does not grant anyone access. The bot account should belong to the team's intended workspace; inviting others or making a file public is not implicit in opening it.

## Implementation

- Bot and backend recognize split “Fig Jam,” “Jam boards,” polite prefixes and launch/open requests. A stale client's `answer` classification is corrected for an explicit board action. Negated and informational requests stay outside action dispatch.
- Bare opening uses no planner/model call. Drawing first verifies the native editor, then makes one bounded existing fast-model board-planning call. Missing authentication therefore costs no drawing inference.
- `meeting_browser_actions` is a typed, capture-scoped durable outbox. Bot-secret authentication, a random claim token, job lease/deadline and active capture are checked. The browser receives `open_figjam` or `draw_figjam`, never generated scripts or arbitrary destinations.
- Native effects require a separate acknowledgment. Pending work is claimed once; uncertain browser writes are not automatically repeated. Recovery of an internal planning snapshot is never treated as a successful Figma write. Cancellation fences delivery and cancels ongoing local browser work; it cannot undo a completed external effect.
- The Figma process starts on demand, muted and separate from Meet. Only a verified board canvas can feed the existing controlled presentation stream. Login, desktop and account DOM are excluded; navigation away from the board suppresses frames.
- The destination mirror starts empty and pauses automatic meeting-note additions. Previous local revisions remain available; they are not silently exported into the new file.

## Current native drawing limits

The browser adapter uses Figma's documented quick actions and accessibility controls to append up to six native sticky notes and straight connectors. It requires native object read-back and rejects mismatched baselines, ambiguous labels, destructive edits and unsupported updates. It does not currently implement general native rename, deletion, move or undo. UI changes can cause an unconfirmed/partial action; these are reported as such rather than successful drawing.

**Actual Figma editor interaction and remote Meet reception remain unverified until the account sign-in is completed.** Chromium fixture tests are not evidence that Figma's current UI matches these selectors. Do not describe this release as live drawing acceptance.

## One-time account setup

Run `backend/bot/generate_figma_auth.py` with the existing Playwright dependency and a desktop display. Sign in manually as the account Wilco should use; complete any account consent yourself. The helper only saves from Figma's `/files/` browser after confirmation and creates no board. It writes `backend/bot/data/figma-auth.json` when invoked with that output path, with mode 0600. The path is ignored by Git. Never send the credential through chat, logs, a pull request or an artifact upload.

Provision it to the notetaker's private state volume as `/data/figma-auth.json` using the existing authenticated deployment channel. `FIGMA_AUTH_STATE_PATH` can override the container path. The Google Meet login remains separate. No account session was committed with this change.

## Verification

- Backend regression suite and frontend production build/typecheck pass; exact final counts are recorded in the coordination handoff.
- Native MLflow routing evaluation: 15/15 synthetic commands; dataset `d-3c6b61151b624934b15d3cd86a11236e`, run `1a7392b69fa54ede9dc8f4e34087642c`. This evaluates dispatch, not audio or Figma.
- API tests cover authentication, capture/token scope, cancellation, no duplicate claims, real-URL validation, acknowledgment ordering, and authentication preflight before inference.
- `backend/scripts/validate_figjam_frame.py` ran in Chromium with intercepted synthetic pages: canvas pixels transferred, account DOM excluded and login navigation suppressed frames. It contacts neither Figma nor Google Meet.
- Desktop/mobile Live-page walkthrough with intercepted synthetic API responses: no pairing fields or built-in draft, native file link appears after polling, no horizontal overflow and zero API mutations. The outbound control uses native link semantics.
- Read-only production diagnostics confirm Google Meet authentication is present and Figma authentication is absent (workflow `43690812256`). The local Figma sign-in window is pending the account holder; no session has been provisioned.
- No new end-to-end latency or throughput result is claimed. Opening avoids inference, browser work is separate from recording/intake, and the existing bounded workers/deadlines remain in force.

## Primary references

- [Figma: create a meeting board](https://help.figma.com/hc/en-us/articles/14942424871575-Create-your-first-meeting-board-in-FigJam): native new-file URLs.
- [Figma: use FigJam with a screen reader](https://help.figma.com/hc/en-us/articles/14477051168791-Use-FigJam-with-a-screen-reader): quick create, text editing, accessibility and keyboard controls.
- [Figma: remote MCP installation](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation/): approved clients and authorization. Ordinary Figma OAuth credentials do not automatically authorize a custom Wilco MCP client. No approved-client impersonation or private API bypass is used.

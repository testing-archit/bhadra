# Voice whiteboards and meeting presentation

Status: deployed at `25fec90`; presentation enabled for acceptance testing on production. Real Meet remote reception remains unverified. Reviewed 15 November 2026. See the [release verification](meeting-action-agent.md#production-release-15-november-2026).

Current default: the bot now requests [native FigJam](voice-figjam-reliability.md), with a paired plugin and shared file. This document retains the earlier internal-board/canvas prototype. Private FigJam presentation uses a participant's normal tab share; it is not automatically captured by the bot.

## Mermaid diagrams (15 November 2026)

Architecture, sequence, ER, class, state and flow diagrams are drawn as **Mermaid** on Wilco's own board, so they need no FigJam sign-in.

- **Voice:** "Wilco, architecture diagram bana do", "draw the system architecture", "sequence diagram dikhao for checkout". `board_intent.wants_diagram` sends these (and later edits to the same board) with `board_provider='internal'`. Other board requests still use FigJam.
- **Planner:** a new `set_diagram` operation (`board_commands.py`) stores a node of kind `diagram` whose `text` is the Mermaid source. It's created once and then updated in place by `node_id`. `card ↔ diagram` swaps are refused.
- **Safety:** `app/services/mermaid_safety.clean` runs on voice edits and manual saves. It accepts known diagram types only, strips code fences, and refuses `%%{init}` directives, `click`/`href` lines, HTML and `javascript:` (`tests/test_mermaid_diagrams.py`). Every renderer uses `securityLevel: 'strict'`.
- **In Meet:** `bot/mermaid_render.py` renders the board's latest diagram in a separate headless Chromium (never the Meet tab) with the vendored `bot/assets/mermaid.min.js` (MIT, `mermaid.LICENSE`). It hands the PNG to the existing presenter as `frame_image`. If Mermaid can't render it, the normal card board is shown.
- **Web app:** the meeting board renders diagram nodes with `mermaid` (loaded only when needed), has an **Add diagram** button, and edits the Mermaid source in the side panel.
- **Not yet:** Excalidraw editing (step 2), and real-call acceptance of the Mermaid presentation path.

## What the bot can do at this checkpoint

| Capability | Implementation and validation |
| --- | --- |
| Open a board | Creates/selects the existing live meeting board and posts its authorized link |
| Follow-up voice edits | Structured create, rename, text update, move, connect, and remove operations; model planning is outside database locks |
| Draw a flow in one request | Temporary node references let the planner add nodes and their connections together |
| Protect collaborative edits | Expected-version checks, locked-node protection, preserved source metadata and human origin, bounded graph sizes |
| Retry an applied edit | The command UUID is stored in revision history; replay returns the existing result without another write |
| Undo | Restores the preceding snapshot only when the latest revision is a voice edit; intervening human edits block undo |
| Present automatically | Experimental Meet adapter, off by default with `PRESENT_BOARD=0` |
| Update the presentation | Immediate redraw after voice edits; two-second state polling picks up other saved changes |
| Stop presentation | Stops canvas tracks, clears painting timers, and uses Meet's stop control when available |

“Open” means creating/selecting the shared artifact and posting a link. It does not open tabs on other participants' computers. The board link retains existing authentication and invite-based access.

Voice operation execution and persistence are tested with generated model responses mocked. These tests do not establish model accuracy on real English/Hinglish audio. Real Meet presentation has not been verified.

## Example workflow

1. “Wilco, open a whiteboard.”
2. “Wilco, draw a flow with signup, verification, payment, and activation.”
3. “Wilco, move verification before payment.”
4. “Wilco, rename signup to create account.”
5. “Wilco, undo that.”
6. “Wilco, present the board.”
7. “Wilco, stop presenting.”

“Wilco, open and present a whiteboard” combines opening and presentation. Every follow-up still needs the wake name; unrelated conversation must not become an edit. Legacy “Charcha” commands remain accepted. Explicit task capture retains its original route even when a task description mentions the board.

Ambiguous references should produce a clarification. Locked points require unlocking through the board UI. Explicit voice edits pause autonomous caption-based additions; the existing Resume AI control enables those again.

New voice-created points are AI drafts. They do not create real tasks, send mail, or create Jira tickets. Those external workflows remain separate planned work. Failed or uncertain external outcomes must never be inferred from board edits.

## Presentation implementation

The bot's own browser receives an opt-in initialization script. Only after an explicit presentation request, its display-media adapter supplies a canvas video track. The canvas contains the board and does not capture the desktop, meeting UI, account pages, or microphone audio. Credentials remain in the Python bot, not the canvas/page URL.

The Python adapter clicks Meet's Present now control and checks for both a live track and a local Stop presenting control. This is a local state check, not evidence that another meeting participant received the content. Host permissions and Meet UI changes can prevent sharing.

The board is painted at a modest cadence so a WebRTC subscriber joining after the first frame still receives it. The read-only presentation fits the current graph to a 1280×720 canvas. Large boards will need focus/pan controls before this becomes a polished presentation experience. The web board's existing polling interval is unchanged.

For other installations, enable a controlled acceptance session by adding `PRESENT_BOARD=1` to `backend/bot/.env` and recreating the notetaker service. This is off by default. The authorized production test release has it enabled. Teams presentation is not enabled.

## Tools and workflows researched

| Option | What the documentation supports | Tradeoff and proposed use |
| --- | --- | --- |
| Existing bot + canvas stream | Browsers can turn a canvas into a MediaStream video track using `captureStream()` | Reuses our bot and board; no new vendor dependency. Our Meet integration is a prototype and requires live acceptance |
| Google Meet add-on | A side panel can start an activity with the board in the main stage; attendees join through an activity notification | Official embedded collaboration workflow; requires add-on deployment/installation and supported attendee clients. Suitable for a later polished collaboration surface |
| Recall.ai Output Media | Streams a controlled webpage through a bot camera or screen share, including Google Meet | Managed alternative if maintaining our browser adapter becomes costly. Requires a separate account/integration and a cost/quota review; no vendor enrollment or purchase was performed |

The official add-on workflow does not automatically force every attendee into our board. Google's documentation distinguishes installed users, users directed to install, and unsupported clients. The canvas API documentation establishes the media primitive; it does not establish that overriding a bot browser's display-media method is an officially supported Meet integration.

Primary references:

- [Google Meet add-on collaboration](https://developers.google.com/workspace/meet/add-ons/guides/collaborate-in-the-add-on)
- [Google Meet add-on quickstart](https://developers.google.com/workspace/meet/add-ons/guides/quickstart)
- [Recall.ai Output Media](https://docs.recall.ai/docs/stream-media)
- [Recall.ai Output Media endpoint](https://docs.recall.ai/reference/bot_output_media_create)
- [Canvas captureStream](https://developer.mozilla.org/en-US/docs/Web/API/HTMLCanvasElement/captureStream)
- [Display capture API](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia)

## Validation and remaining acceptance

Validation used a disposable local Postgres database, synthetic board content, and local Chromium. No real meeting, account recording, provider inference, Jira write, or mail send was used.

- Full backend suite: **434 passed**. Additional targeted board checks passed after strengthening undo/polite-command handling.
- API/operation tests cover bot authentication, duplicate commands, stable node IDs, complete flows, invalid references, locked points, invalid coordinates, preservation of human edits, safe undo, and concurrent edits during planning.
- Local browser test: canvas video transmitted through two real WebRTC peers, a received frame was inspected, a live update appeared, repeated presentation preserved the stream, and stop ended it.
- Preview: [synthetic received video frame](screenshots/wilco-board-presentation-prototype.png).

Reproduce the media test with Playwright installed:

```bash
python backend/scripts/validate_board_presentation.py --chromium /path/to/chromium --screenshot /tmp/wilco-board-presentation.png
```

Before enabling broadly, run an authorized two-person Meet session and check: actual remote video reception; voice editing while presenting; late joining; host restrictions; stop/restart; recording continuity and audio quality; CPU/RAM under concurrent calls; caption accuracy; ambiguous references; and end-to-end latency. Verify success from the other attendee's device. A local presenting indicator alone is insufficient.

Keep `PRESENT_BOARD=0` if the live acceptance fails. The existing board-link plus manual tab-sharing workflow remains usable.

## Durable command pipeline follow-up

Model-bound board edits now run through the [durable action agent](meeting-action-agent.md).
The bot acknowledges acceptance, reports progress, and recovers saved results. Board
creation and compound drawing/task requests use the same job ledger. Spoken cancel,
speech-stop, and status controls bypass normal execution. The legacy board endpoints
remain compatible; the current bot needs the updated backend and initialized schema.
Presentation remains opt-in and still needs real Meet remote-reception acceptance.

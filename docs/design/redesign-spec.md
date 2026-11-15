# Wilco redesign: implementation spec

Status: approved direction, ready to build (15 Nov 2026).
Visual reference: the "Wilco redesign" Design canvas (link from the team). It has seven artboards: Landing, Home, Meeting debrief, Tasks, Memory, Mobile Home and Design system. When this spec and the canvas disagree, this spec wins.

Read `PRODUCT.md` and `docs/coordination.md` before editing shared files. The direction contract is in `.impeccable/surfaces/frontend-src-app-app-dashboard-page-tsx.md`.

## 0. The idea in one paragraph

Wilco uses an **ink frame around bright working sheets**, with **one signal-yellow voice**. The dark parts (sidebar, hero bands, the landing page) are where Wilco *hears*; the white sheets are where things get *written down*. Yellow only means "voice and action": record, ask, the active nav notch, the key button, and the decision ticks on the **Debrief strip**. The strip is the signature move: a thin talk-timeline per meeting, with a tick at the moment each decision or task was said. It appears on the landing hero, Home, the meeting page and Memory citations.

What it replaces: the pastel band, teal pills, orange buttons and the "every surface is a white card" look in the current Home, Tasks and Memory screens.

## 1. Non-negotiables

- **Behaviour, routes, APIs and privacy rules do not change.** This is a visual and layout pass. Every existing action (Done, Snooze, Reassign, Undo, Jira send, sharing, confidential handling, capture consent) keeps its current API call and states.
- **No invented data.** Counts, strips and chips come from real API data. The canvas uses sample content; do not hard-code it.
- **Yellow `#FFD60A` is never text on a light surface, and never a border on white.** On white, use ink.
- **No eyebrow or kicker labels above headings, no gradient text, no glass, no coloured left borders on cards or rows.** The only gradient is the radial "aurora" in the landing hero and Home band.
- Light and dark are both first-class. WCAG AA in both. Full keyboard use. `prefers-reduced-motion` turns every animation into its end state.
- Stay on the current stack (Next 16 / React 19 / Tailwind 4, Base UI primitives, Lucide icons). No new UI libraries are needed.
- Use only `example.com` addresses and synthetic data in anything committed.

## 2. Tokens (`frontend/src/app/globals.css`)

Replace the current palette values. Keep the existing token *names* that shadcn and the components already use, and add the new ones. Components use tokens only, never raw hex.

### Light

| Token | Value | Use |
|---|---|---|
| `--frame` (new) | `#0B0B0C` | Sidebar, bands, landing background, mobile tab bar |
| `--frame-foreground` (new) | `#F4F4F5` | Text on the frame |
| `--frame-muted` (new) | `#B4B4BC` | Secondary text on the frame (also `#8A8A93` for meta, ≥4.5:1 on frame) |
| `--frame-line` (new) | `#26262B` | Borders on the frame |
| `--graphite` (new) | `#161619` | Sheets that sit on the frame (strip card, landing stage) |
| `--background` | `#EEEDEA` | App canvas ("stone") behind sheets |
| `--card` / `--popover` | `#FFFFFF` | Working sheets |
| `--foreground` | `#141416` | Body text |
| `--muted-foreground` | `#5E5E66` | Meta text (6.3:1 on white) |
| `--border` / `--input` | `#E2E0DB` / `#D6D4CE` | Hairlines / input borders |
| `--muted` | `#F1EFEA` | Neutral chips, hovered rows use `#F6F5F2` |
| `--primary` | `#0B0B0C` | Primary button on a sheet (ink, white text) |
| `--primary-foreground` | `#FFFFFF` | |
| `--signal` (new, replaces `--marigold`) | `#FFD60A` | Key action, record, ask, nav notch, strip ticks on ink |
| `--signal-foreground` | `#0B0B0C` | Text on yellow |
| `--signal-hover` | `#FFE34D` | |
| `--selection` (new) | `#FFF8CC` + 1px inset `#E8C800` | Selected list row on a sheet |
| `--ring` | `#2563EB` on sheets; `#FFD60A` on the frame | Focus ring, 2px, offset 2px |
| `--destructive` | `#DC2626` | Unchanged role |

Tints (chips and status pills only, always background + its foreground):

| Tint | Background | Foreground | Meaning |
|---|---|---|---|
| peach | `#FDE3D3` | `#7A3412` | Due soon, needs review |
| lilac | `#E7E1F7` | `#3F2D73` | People, owners |
| mint | `#D9F2E4` | `#14532D` | Confirmed, Wilco will join |
| rose | `#F9DCE3` | `#7A1F3D` | Confidential |
| sky | `#DCEBFA` | `#1E3A5F` | In Jira, info, brief ready |

### Dark

The frame stays ink. Sheets become graphite, and nothing is inverted.

| Token | Value |
|---|---|
| `--frame` | `#050506` |
| `--background` | `#0F0F11` |
| `--card` | `#18181B` |
| `--foreground` | `#F4F4F5` |
| `--muted-foreground` | `#A1A1AA` |
| `--border` | `#26262B` |
| `--primary` | `#F4F4F5` (light button, ink text) |
| `--signal` | `#FFD60A` (unchanged; on dark sheets, strip ticks may be yellow) |
| `--selection` | `#2A2610` + inset `#8A7400` |
| Tints | Same hues at ~18% opacity on graphite, with foregrounds lifted (e.g. peach fg `#FDBA8C`). Check each pair ≥4.5:1 |

### Theme the browser too

- `::selection { background: var(--signal); color: var(--signal-foreground) }`
- `font-variant-numeric: tabular-nums` on the app body.
- `accent-color: var(--primary)`.
- Scrollbars use thin thumbs in `--border`.

### Type (fonts already loaded in `src/app/layout.tsx`)

- Geist for everything. Mukta is the Devanagari fallback (already in the stack). Geist Mono is only for timestamps and keyboard shortcuts. Doto 900 is only for the Home counts (always two digits: `04`).
- Landing display: 600, `clamp(48px, 7.2vw, 96px)`, line-height .95, tracking −0.045em. Section h2: `clamp(36px, 4.4vw, 56px)`, −0.04em.
- App page title: 34px/600/−0.035em (40px on the Home band). Section heading: 17px/600. Row title: 15px/500. Body: 15px/1.55. Meta: 13px muted.
- **Two-tone headings:** the first clause is in the foreground colour, the second in `#6E6E78` on ink or `#8A8780` on stone. Example: "Heard. *Will comply.*", "Tasks *· 4 yours, 3 waiting*". Use this on page titles and landing headings only.

### Shape and depth

- Radii: sheet 20, band 24, input 12, nav item 10, pill 999.
- 1px borders; no card shadows. Shadows only on the floating landing nav, the Memory composer, popovers and the mobile tab bar.
- The app content area is a stone "tray" with `border-radius: 20px 0 0 20px`, inset 8px from the window top and bottom, sitting on the ink frame. On mobile the tray becomes a top sheet with `24px 24px 0 0`.

## 3. Shared components to build or restyle

| Component | Where | Notes |
|---|---|---|
| `DebriefStrip` (new) `components/meeting/debrief-strip.tsx` | Home band, Home recent rows, Meeting header, Memory sources, landing | Props: `segments: {start_ms, end_ms, text}[]`, `marks: {at_ms, kind: 'decision'|'task'|'risk', label, segmentId}[]`, `duration_ms`, `variant: 'ink'|'sheet'`, `size: 'sm'|'md'|'lg'` (22/44/64px tall), `onMarkClick`. Split the meeting into N buckets (40 sm, 64 md, 120 lg); bar height = words spoken in that bucket, normalised. Marks come from each task's or decision's `evidence[0].segment_id`, mapped to that segment's `start_ms`. Ticks fill the full height: yellow on ink, ink on a sheet. With no segment timing, render no strip (never a fake waveform). Bars are `aria-hidden`; marks render as a real list of buttons below the strip on the lg variant ("09:21 Task · submission checklist") that open the evidence quote. |
| App shell `app/(app)/layout.tsx`, `components/shell/*` | All app routes | Ink sidebar, 232px: wordmark, a yellow "Bring Wilco to a meeting" button (opens the existing capture dialog), a Search ⌘K trigger (existing command palette), nav (Home, Meetings, Tasks with an open-count, Memory, Talk to Wilco, Calendar, More for the rest of `nav-config.ts`), then Settings and the user at the bottom. The active item gets a `#1A1A1D` fill plus a 3×16px yellow notch at the left edge. The top bar inside the tray shows breadcrumb or page name, the theme toggle and the notification bell. |
| `MobileNavigation` | < 768px | A floating ink tab bar 12px from the edges: Home, Meetings, a raised yellow centre "Bring Wilco" button, Calendar, Memory. The profile avatar (top right) opens full navigation, including Settings. Keep the existing pathname and calendar-query logic. |
| Buttons (`components/ui/button.tsx` variants) | Everywhere | `signal` (yellow, ink text) for the one key action per view; `default` = ink; `outline` = white with a `--input` border; `ghost`. Pill radius for actions, 12px radius for form-adjacent buttons. Min height 40 (44 for primary touch targets). Keep the label and add a spinner while busy. |
| `Chip` / status pill | Rows, debrief | Tint background + tint foreground, 12px, pill. Never colour alone: always text. |
| `CountLink` | Home band | Doto two-digit number + 13px label, rendered as a link to the filtered list. Only real counts. |

## 3b. Engagement pass (overrides section 4 where they differ)

There are three rules on every screen:

1. **Minimum text.** One line where there was a paragraph. Labels are 1–3 words ("Confirm", "Next", "Ask", "Sources", "Nudge"). Never explain a control next to the control. Headings are two short clauses.
2. **No dead space.** At 1280–1600px, no column ends while its neighbour keeps going: sibling panels stretch to equal height (`align-items: stretch`, with `flex: 1` on the last child), and side gutters become a live panel. Section padding is 88px on the landing page and 20–24px in the app.
3. **Show by doing.** Every section has one thing to tap that changes what you see. In the app these are real actions on real data. On the landing page they are scripted demos built from the seeded meetings.

| Surface | Interaction (built in the canvas; implement it like this) |
|---|---|
| Landing hero | Moment chips under the waveform (14:02 Task, 14:09 Decision, 14:15 Task). Tapping one replays from that tick: the waveform fills to the tick, the line resolves word by word, and the result card (kind chip, title, owner) lands. Tick bars are taller and white once played. |
| Landing "How" | A tablist of 4 steps (Joins · Answers out loud · Debriefs · Follows up) with a 4s progress underline that auto-advances until the user clicks. The ink panel on the right swaps per step: Meet tiles with Wilco highlighted, then a spoken Q&A bubble pair, then a mini strip with 3 item rows, then Wilco ⇄ Jira cards. |
| Landing "Languages" | A segmented toggle (Hinglish / हिंदी / English) changes the spoken line; the extracted "Decision: Use PostgreSQL" card stays the same. That is the whole argument, without a paragraph. |
| Landing "Privacy" | Viewer chips (Organiser, Invited, Not invited, Admin) with a green or red dot. A confidential meeting card blurs its content (6px) for viewers who can't open it, and shows a verdict line with a check or lock icon (SVG, not a text glyph). |
| Landing CTA | Prompt chips above the ask bar; the answer streams with a citation pill. |
| Home band | The latest meeting's strip ticks are buttons. Tapping one shows its quote and time under the strip, next to "Review". Counts (Doto) update live as tasks are completed, and the headline follows ("Three things left."). |
| Home follow-ups | The circle check fills ink with a white check, the row dims and strikes through, and an ink Undo bar slides up inside the sheet. Waiting-on shows as initials in the header, not a sentence. |
| Home ask | Ink panel with three question chips. Selecting one shows a one-line answer, with an input and mic under it. It never answers on page load: the chip click is the request (this keeps the "no AI call on load" rule). |
| Home recent | A 3-up grid of compact meeting tiles (title, state pill, strip, one meta line) instead of rows. |
| Meeting | The strip ticks drive a **Moment** panel (kind, time, title, speaker, quote, ‹ › and Listen). **Confirm** is an ink panel: question, item, 2–3 answer buttons, and every tap advances the yellow progress bar; at the end it shows "All confirmed." **Out of this meeting** is one list with an All / Decisions / Tasks filter, and selecting a row also moves the strip. "Send 3 to Jira" changes to "In Jira · 3". The summary moves behind the Listen button and the Insights tab. |
| Tasks | Date-rail days filter the list, and dots show days with work. Clicking a row selects it (yellow selection) and the ink dock acts on it: Done, +1 week, Reassign, Jira, then Undo. The empty filter result reads "Nothing due that day." with a "Show all" button. A right column of Waiting-on person cards has a Nudge button that copies a reminder and changes to "Copied". |
| Memory | Two columns. Left: question chips, the conversation sheet, and the composer pinned inside the sheet. Right: **Sources** cards with a strip showing the cited tick, plus an ink **Related** panel of follow-up questions. Citation numbers are buttons that select their source (the selected card gets a 2px ink border and the others drop to .7 opacity). |
| Mobile Home | Tasks tick off in place and the counts and headline update. |

All of these use the existing APIs (task done/undo/snooze, review confirmations, Jira send, memory ask). No new endpoints. Under reduced motion, every sequence shows its end state, and auto-advance stays off.

## 4. Screens

### 4.1 Landing page: new, at `/` for signed-out visitors

`src/app/page.tsx` currently redirects. New behaviour: signed in → `router.replace('/dashboard')` (unchanged); signed out → render the landing page (move it into `src/app/(marketing)/landing.tsx` or similar). `/login` stays as it is, restyled with the same tokens: ink left panel with the hero headline, white sign-in sheet on the right.

Sections in order (see the Landing artboard):

1. **Floating ink pill nav**, sticky 16px from the top, centred: the Wilco mark, How, Languages, Privacy, Sign in, and a yellow "Try it" button. The hero subcopy is one line, "Meetings in Hinglish, notes with owners.", with platform pills under the buttons; the separate "Where it works" strip is removed. On scroll past 80px, reduce the padding (transform and padding transition, 150ms). Below 640px the links collapse into a menu button; the yellow button stays.
2. **Hero (ink):**
   - Left column: the two-tone h1 "Heard. / Will comply.", the 19px subcopy, a yellow "Try the demo" button (scrolls to #ask) and an outline "Add the Chrome extension" button (→ `/extension`), plus the line "Hears with Gnani Prisma v3 · Speaks with Gnani Timbre".
   - Right column, **the stage**: a graphite card with the meeting name, a 14:02 IST stamp, a waveform and a Hinglish line, and below it a white task sheet that lands into place.
   - The mascot (`public/brand/wilco-mascot-v1.png`, about 92px) sits under the stage next to "Play it again".
   - There is one radial aurora behind the right edge.
3. **Where it works:** a one-line strip with hairline borders top and bottom: Google Meet, Microsoft Teams, In person from your phone, Uploaded recordings, Calendar auto-invite.
4. **How it works (stone):** the heading on the left; on the right, one white sheet holding a 4-row ruled list with mono times (14:00 joins, 14:12 asked in the call, 14:31 debrief, Later Jira and memory). This is not a card grid.
5. **Languages (white):** an ink card with the Devanagari Hinglish line next to a stone card with "Decision: use PostgreSQL / Reason …" plus chips.
6. **Privacy (stone):** "Only the room reads the notes." A `<dl>` with three ruled rows: Invite-based, Held tasks, Confidential meetings. Copy must match the real rules in CLAUDE.md.
7. **Live CTA (ink), `#ask`:** "Ask it something." A graphite ask bar reads "Wilco, {question}" and has a yellow mic button. The answer streams in word by word (55ms per word, blur 3px → 0) and then shows a citation pill with the meeting, date and time. Below are three prompt chips that switch the question. Answers are scripted from the seeded demo meetings and labelled "from the sample meetings in the demo workspace". Under the chips is a yellow "Sign in and ask your own meetings" button. Optional: play the answer with Timbre through the existing TTS route when the mic button is pressed (only if it works without sign-in; otherwise leave it silent).
8. **Footer (ink):**
   - "Heard. Will comply." and the line "Built by team Bhadra for Gnani AI's Great Indian AI Internship Challenge".
   - Three link columns: Product, Get started, Trust.
   - A giant **WILCO** wordmark in `#1A1A1D` that runs off the bottom edge (`clamp(120px, 27vw, 400px)`, overflow hidden, `aria-hidden`).

**Hero signature animation** (plays once on load; "Play it again" replays it; reduced motion shows the end state):

1. 0–2.0s: the 56 waveform bars fill left to right from `#2E2E34` to yellow (2 bars every 70ms).
2. Then the transcript words resolve one at a time (opacity .12 → 1, blur 3px → 0, 70ms apart): *"Archit, Ramesh ji ke saath Marathi read-aloud test kar lena, Sunday tak."* (speaker: Riya).
3. After 350ms the white task sheet lands: opacity 0 → 1 and translateY 12px → 0, over 420ms on `cubic-bezier(.16,1,.3,1)`. It shows "Test Marathi read-aloud with Ramesh ji", the Owner and Due chips, "Heard at 14:02", and "Sent to Jira".

Nothing else on the page animates on load. Section reveals are not needed.

### 4.2 Home: `app/(app)/dashboard/page.tsx`

The behaviour stays exactly as `DESIGN.md`'s Layout and `docs/home-follow-through.md` describe (real counts, Undo, no AI call on load).

- **Ink band** (radius 24): the two-tone greeting ("Good morning, Archit. / Four things are yours.") and three `CountLink`s (open follow-ups; due soonest, in yellow; details to confirm). On the right is a graphite card for the **latest meeting**: title, date and duration, a md `DebriefStrip` (ink variant), "3 decisions · 3 tasks", and a yellow "Review notes" button. When there is no meeting yet, show the mascot with "Bring Wilco to your next meeting" and the capture button.
- **"Yours to move"** sheet: the existing follow-up rows (circle check, title, source meeting, due chip), with the footer row "Waiting on Vedant, Riya and Sam · 3 open".
- **Right column:**
  - "Coming up": the next event with date block, time in IST, platform, and chips for "Wilco will join" and "Brief ready 10:50". Keep the existing connect and empty states.
  - "Ask your meetings": an input, an ink mic button with a yellow glyph, and two starter links into Memory.
- **Recent meetings:** rows with title and meta, a sm `DebriefStrip` (sheet variant), the follow-up count, and a status pill (peach "6 to confirm" or mint "Confirmed").
- Record in person, Upload and Voice setup stay reachable from the capture dialog and "More".

### 4.3 Meeting: `app/(app)/meetings/[id]/page.tsx`

- Breadcrumb "Meetings / title" in the tray top bar.
- **Ink header band:**
  - Title, date and time in IST, platform, and an access pill ("Invited only · 4 people"; rose "Confidential" when flagged).
  - Actions: outline "Share" and yellow "Send N tasks to Jira" (hidden for confidential meetings and when Jira isn't connected).
  - Below: an lg `DebriefStrip` with an IST time axis and the list of mark buttons. Clicking a mark selects it (yellow border) and scrolls to the item, with its quote highlighted.
- Tabs: Debrief · Transcript · Insights · People (map onto the existing tabs; keep `?tab=` query names).
- **Debrief tab**, two columns:
  - Left:
    - "Confirm what Wilco wasn't sure about": the existing one-at-a-time review, with a progress bar in ink, the item type, the item text, the evidence quote in a stone block with its mono timestamp, and choices as 44px buttons (the selected one is ink). Plus Skip.
    - Then "Decisions": ruled rows with a mono time, title and reason.
  - Right:
    - "Summary" with the Timbre "Listen" button.
    - "Tasks" with owner, due and Jira chips.
- The Transcript tab keeps its current functions, restyled: speaker name 13px/600, the text, a mono time, and the strip marks in the gutter.

### 4.4 Tasks: `app/(app)/tasks/page.tsx`, `components/task-workspace.tsx`

- Title: "Tasks · 4 yours, 3 waiting" (two-tone, from real counts) and an ink "Add task" button.
- A segmented control for Mine / Waiting on others / Unassigned / Everyone (maps to the existing `?scope=`). On the right: search, List·Board, Filters.
- **Ink date rail** replaces the pastel gradient rail. The selected day is yellow with ink text; days with tasks get a yellow dot; "All" comes first.
- The list sheet uses the selected row style `--selection`. The **action dock** sits at the bottom of the list sheet in ink: the context text, a yellow Done, and outline Snooze, Reassign and Send to Jira. Undo appears as a toast after Done. The menus stay Base UI.
- The "Waiting on" sheet has person pills with initials in tint colours, a count per person, and "Copy a reminder".
- The Board view uses the same row styling inside columns.

### 4.5 Memory: `app/(app)/memory/page.tsx`

- Top bar: a scope pill ("Searching all 10 of your meetings", which opens the existing source picker), plus History and New chat.
- Empty state: the two-tone heading "It's in your meetings. / Let's find it.", the small mascot, the composer, three starter chips, and three recent meetings (keep the current behaviour).
- Conversation:
  - The user's message is an ink bubble on the right.
  - The answer is 18px/1.65 text with superscript citation numbers, then Listen and Copy, then **source cards**: meeting title and time, a sm sheet `DebriefStrip` with only the cited moment ticked, and the quote in its original language.
- The composer is sticky at the bottom with a soft shadow: a textarea, a yellow mic button and an ink send button. On mobile it sits above the tab bar.

### 4.6 Live, Record, Settings and the rest

- **Live (`/live`):** an ink full-bleed screen. The mascot is centred at about 160px; its listening and speaking states use a yellow ring pulse (scale 1 → 1.06, 1.2s, paused under reduced motion). The live transcript sits on graphite and the barge-in hint in muted text. This is the third place the mascot is allowed (landing, empty states, Live).
- **Record, Settings, Admin and Vocabulary:** apply the tokens, shell and components only. No layout changes.
- **Chrome extension popup and in-Meet overlay:** out of scope for now. Note it in `DESIGN.md`.

## 5. Motion

- Durations: 120ms (hover and press), 200ms (menus), 420ms (landing land-in). Easing: `cubic-bezier(.16,1,.3,1)`. Animate transform, opacity and filter only.
- One authored moment per surface: the landing hero sequence, and the Live CTA stream. In the app, the only motion is task completion (check fills, then the row collapses over 200ms) and strip-mark selection.
- `prefers-reduced-motion: reduce`: no sequences, final states only.

## 6. Build order (one commit per step, `npm run typecheck` after each)

1. Tokens in `globals.css` (light and dark) plus the browser surfaces. Replace `--marigold` usages with `--signal`; remove the feature-band gradient tokens.
2. App shell: sidebar, tray and top bar, then the mobile tab bar.
3. Button and chip variants.
4. `DebriefStrip` with a small pure function `buildStrip(segments, marks, buckets)` that has its own unit test.
5. Home.
6. Meeting debrief header and Debrief tab.
7. Tasks.
8. Memory.
9. Landing at `/` and the `/login` restyle.
10. Live screen.
11. Run the impeccable finish review and the `document` pass: regenerate `DESIGN.md` from the built result, and update the "Design system" section of `CLAUDE.md`, which still describes the old night-glow look.

## 7. Done when

- `cd frontend && npm run typecheck` passes.
- Every screen above has been checked at 1440 and 390 wide, in light and dark, with real seeded data (`backend/scripts/seed_demo.py`).
- `rg "#[0-9a-fA-F]{6}" frontend/src/components frontend/src/app --glob '!globals.css'` returns nothing new.
- No yellow text on light surfaces, every interactive element is reachable by Tab with a visible ring, and text contrast is AA.
- Existing flows still work end to end: invite the notetaker, review notes, Done/Undo, Snooze, Reassign, Jira send, the memory question with citations, Live.
- `docs/screenshots/` is refreshed with the new captures for the demo video.

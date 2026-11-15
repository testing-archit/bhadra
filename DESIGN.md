# Wilco design system

## Hackathon software-team direction (15 November 2026)

The user rejected the prior workspace UI and now wants a visually ambitious hackathon demo aimed at software companies. This direction supersedes the mascot-led palette and Home composition below where they conflict. Keep the existing product actions, permission rules, recording consent, and honest data states. See [the signal-room design direction](docs/hackathon-ui-direction.md) and its concept image for the new visual target. The image is a concept with invented data; the implementation must use actual application state.

The approved v1 browser mascot now governs Wilco’s identity: soft pink, lilac and sky blue, charcoal linework, teal shorts, and orange cap/shoes. Use these colours with the existing components and live meeting/task flows. The image-model references in `docs/design-references/` guide the visual direction; they are not application data.

## Layout

Home starts with the compact greeting and a pastel latest-meeting band containing the approved mascot, Review notes and Invite Wilco. A connected panel shows four urgent owned follow-ups with completion and Undo, plus honest progress across the owned tasks returned by the API. A compact schedule and a user-initiated memory question sit alongside it; recent notes use short rows below. Record in person, upload and optional voice setup remain reachable as utility links. Do not invent activity, completion goals or urgency to fill space.

Desktop has a white sidebar and two content columns. Mobile has a bottom bar for Home, Meetings, Calendar, and Settings, plus a central invite button. The profile button opens full navigation so secondary tools remain reachable. Calendar has Ongoing, Upcoming, and History tabs, week controls, tappable dates, real meeting links, and the existing auto-invite switches.

## Palette and type

Define colours only in `frontend/src/app/globals.css`; components use theme tokens.

| Role | Light token value |
| --- | --- |
| Canvas | `--background: #fcfaf8` |
| Surface | `--card: #ffffff` |
| Copy | `--foreground: #24262c` |
| Secondary copy | `--muted-foreground: #65616c` |
| Primary / selection | `--primary: #126b75` |
| Selected surface | `--accent: #e1f1f0` |
| Key action | `--marigold: #ff9b17`, with charcoal text |
| Pastel band | `--feature-top: #f4c9e4`, `--feature-middle: #dfd2f2`, `--feature-bottom: #bcdcf7` |

Light remains the default; saved theme preferences are respected. Dark mode uses warm charcoal surfaces, light teal selections, and orange key actions. Primary text/action token pairs were checked for contrast in both themes. Use gradients only for the welcome band and the task date rail; do not wash every surface in colour.

Geist carries the interface; Mukta remains the Devanagari fallback. Use compact sentence-case headings and body text. No oversized Home slogan or decorative counters.

## Components

- `RecordedMeetingCard` remains the Meetings list card. Home uses compact recent-note rows; keep processing and attention states visible.
- `MeetingPeople` shows initials from the actual attendee names. Do not substitute stock portraits for real identities.
- `MeetingAgenda` has a compact Home mode with the next two live/upcoming events, and a full Calendar mode where dates filter events and tabs select event state. Show honest connection, empty and error states.
- `MobileNavigation` reflects both pathname and calendar query state. Its central action opens the existing capture dialog.
- Existing Base UI primitives handle dialogs, tabs, menus, and focus behaviour. Keep Lucide as the icon family.

## Behaviour and trust

Joining opens the event's meeting link. Inviting Wilco pre-fills the existing recording-consent form. A calendar's auto-invite switch uses the existing per-event API and reports failure without pretending the setting changed.

One task, decision, or uncertain speaker is reviewed at a time. Inline edits and source evidence remain available. Uncertain speakers can stay unnamed; using a correction for future voice matching has a separate opt-in. Detailed transcripts and insights remain behind Full meeting.

Home review counts require both meeting details and speaker data; failed reads must not imply confirmation. Task progress includes completed and open owned tasks, excludes delegated work, and does not claim a weekly goal. Home never generates an AI answer on load: a submitted or clicked question uses the existing Memory flow. See `docs/home-follow-through.md` for the behavioural rationale and validation.

## Motion and accessibility

Use short interaction feedback, visible focus, labelled controls, and reduced-motion support. Hover changes are small and purposeful. The mascot is static and limited to the welcome/navigation areas; working surfaces retain clear text and restrained borders. Avoid background animation and simulated recording indicators. Keep recording consent, errors, confidentiality, and sharing rules explicit.

See `docs/coordination.md` before editing shared files and `docs/ui-reference.md` for previews and verification.

## Tasks

A connected Flow replaces the rejected deck and disconnected card grid. Keep multiple full task titles visible in one surface. A compact date rail filters actual due dates; All includes undated, overdue and later work too. The selected row receives a teal cue. The shared action dock changes its meeting source and owner without expanding task rows or moving the overview.

Done, Snooze, Reassign, Edit and Undo use existing APIs. Snooze and reassignment use accessible Base UI menus over the working surface. Failed saves preserve selection; Undo remains available after the last task. Restricted meetings never get a link. Search stays visible; advanced filters remain disclosed. List/Board, completed tasks, exports and bulk tools remain available.

Use short transform-only settling after task mutations, no animated backgrounds or looping mascot. Respect reduced motion. The Waiting on strip is derived from accessible delegated tasks and opens the selected owner’s waiting list.

## Memory

Memory uses one central workspace. The initial composer sits beside the approved mascot heading, followed by three short editable question starters and three real recent meetings. Avoid a permanent second sidebar or duplicate explanatory headings. History opens in a labelled dialog; source selection is a draft that applies explicitly, supports up to ten meetings, and preserves the typed question. Cancel leaves the active chat intact; applying unchanged sources preserves the conversation. Answers retain citations, source links and voice controls. The active composer fits above mobile navigation.

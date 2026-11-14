# Wilco design system

The supplied mobile reference image replaces the earlier video-based direction. Wilco now uses a light lilac canvas, white rounded surfaces, violet actions, compact meeting cards, and direct navigation. The interface is organised around actual meetings and actions.

## Layout

Home starts with the user's name and a compact greeting. The capture tile sits beside two stacked shortcuts for recording in person and asking past meetings. Recent meetings use cards with the date, duration, a short summary, participant circles, and an Open notes or Review notes action. The focused follow-up queue remains available beside the schedule on desktop and below the meeting cards on mobile.

Desktop has a white sidebar and two content columns. Mobile has a bottom bar for Home, Meetings, Calendar, and Settings, plus a central invite button. The profile button opens full navigation so secondary tools remain reachable. Calendar has Ongoing, Upcoming, and History tabs, week controls, tappable dates, real meeting links, and the existing auto-invite switches.

## Palette and type

Define colours only in `frontend/src/app/globals.css`; components use theme tokens.

| Role | Light token value |
| --- | --- |
| Canvas | `--background: #faf9fd` |
| Surface | `--card: #ffffff` |
| Copy | `--foreground: #24212d` |
| Secondary copy | `--muted-foreground: #706a7b` |
| Action | `--primary: #7d45df` |
| Selected surface | `--accent: #f0e9fc` |
| Capture tile | `--feature-top: #b184ef`, `--feature-bottom: #7741d7` |

The legacy `--marigold` token now follows violet for existing consumers. Light is the default; saved theme preferences remain supported. Dark mode uses the same structure and violet actions.

Geist carries the interface; Mukta remains the Devanagari fallback. Use compact sentence-case headings and body text. No oversized Home slogan or decorative counters.

## Components

- `RecordedMeetingCard` is shared by Home and Meetings. Keep processing and attention states visible.
- `MeetingPeople` shows initials from the actual attendee names. Do not substitute stock portraits for real identities.
- `MeetingAgenda` is shared by Home and Calendar. Dates filter events; tabs select event state. Show connection and empty states when the calendar has no data.
- `MobileNavigation` reflects both pathname and calendar query state. Its central action opens the existing capture dialog.
- Existing Base UI primitives handle dialogs, tabs, menus, and focus behaviour. Keep Lucide as the icon family.

## Behaviour and trust

Joining opens the event's meeting link. Inviting Wilco pre-fills the existing recording-consent form. A calendar's auto-invite switch uses the existing per-event API and reports failure without pretending the setting changed.

One task, decision, or uncertain speaker is reviewed at a time. Inline edits and source evidence remain available. Uncertain speakers can stay unnamed; using a correction for future voice matching has a separate opt-in. Detailed transcripts and insights remain behind Full meeting.

## Motion and accessibility

Use short interaction feedback, visible focus, labelled controls, and reduced-motion support. Hover changes are small and purposeful. The violet capture gradient is confined to its action tile; working surfaces stay white. Avoid background animation and simulated recording indicators. Keep recording consent, errors, confidentiality, and sharing rules explicit.

See `docs/coordination.md` before editing shared files and `docs/ui-reference.md` for previews and verification.

## Tasks

The user rejected the single-card deck as too empty, then chose compact task cards. Cards are now the default. Keep several task titles visible together in a two-column desktop grid, stacking on mobile. Each card shows a completion control, due date, project/source, and the real owner's initial. High priority and in-progress status get explicit labels only when relevant. Don't shorten or rewrite the task itself.

The title or details arrow expands that card's meeting source and Done / Snooze / Reassign actions. Only one card expands at a time. Saving waits for success, errors leave the card open, and Undo remains available after the last task. Restricted tasks never offer meeting links. Search stays visible; advanced filters are disclosed. List, Board, completed tasks, exports and bulk tools remain accessible.

A compact Waiting on strip shows actual owners and pending counts from accessible delegated tasks. Tapping a person opens their waiting tasks. Keep theme tokens, Geist, real data and quiet interaction feedback; don't add decorative metrics, empty columns or invented suggestions to fill space.

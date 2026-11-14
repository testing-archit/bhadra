# Reference UI review

The latest supplied image governs this revision: light lilac canvas, white rounded cards, violet actions, compact meeting metadata, participant circles, and a mobile bottom bar. It replaces the previous dark hero direction.

## Screens

- [Desktop Home](screenshots/wilco-violet-home-desktop.png)
- [Mobile Home](screenshots/wilco-violet-home-mobile.png)
- [Mobile Calendar](screenshots/wilco-violet-calendar-mobile.png)
- [Meeting review](screenshots/wilco-violet-review.png)
- [Recording confirmation](screenshots/wilco-violet-capture.png)
- [Optional dark theme](screenshots/wilco-violet-dark.png)

These are screenshots of the running implementation. The calendar screenshots use synthetic scheduled events to show populated states. Saved meeting cards use local demo meetings. The app does not insert these fixture events into a real calendar; unlinked calendars show an explicit connection prompt.

## Behaviour

Home has a capture action, recording and memory shortcuts, shared meeting cards, a working schedule, and the focused follow-up queue. Meetings uses the same recorded-meeting cards. Participant circles use actual attendee initials rather than invented profile photos.

Ongoing, Upcoming, and History select event state. Date buttons filter events; week arrows change the date strip. Join meeting opens the event's conferencing link. Invite Wilco carries that link into the existing consent form. The auto-invite switch keeps the existing calendar API and reports errors without assuming an update succeeded.

Mobile navigation has Home, Meetings, Calendar, Settings, and a central invite action. Calendar and Meetings remain distinct even though they share a route with different query parameters. The profile button opens the full navigation menu. Light is the default; explicit saved theme choices remain supported.

The previous inline review, unnamed-speaker action, separate voice-learning opt-in, confidentiality, and sharing rules remain in place.

## Verification

Frontend TypeScript and production build passed. Nineteen browser checks covered desktop light and dark, 390px layout, shortcut destinations, schedule tabs, week/date selection, auto-invite switching, mobile calendar routing, central invite action, meeting-link handoff, consent gating, optional settings, capture success, capture failure preserving input, mobile keyboard focus, inline edits, task/decision confirmation, unnamed speakers, progressive meeting details, and reduced motion. No uncaught browser errors were reported.

Mutations were intercepted. Verification did not start a bot, modify a real calendar, change saved meeting notes, or call AI generation services. The real two-person Meet and enrolled-voice acceptance test remains separate work.

## Local preview

The isolated frontend runs at `http://localhost:3200`, with a local-only proxy on 3300 forwarding to the existing backend on 8000. The reviewed files are also copied into the shared checkout after checking for concurrent edits. Checkpoint pushes use the UI topic branch; production remains unchanged.

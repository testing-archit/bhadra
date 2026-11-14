# Reference UI review

This pass applies the supplied video's dark canvas, cool perimeter light, generous spacing, and compact input to Wilco's main meeting workflow. The Home atmosphere is static. Task, meeting, and review content stays on neutral surfaces.

## Screens to review

- [Dark Home](screenshots/wilco-home-dark.png)
- [Light Home](screenshots/wilco-home-light.png)
- [Mobile Home](screenshots/wilco-home-mobile.png)
- [Meeting review](screenshots/wilco-review-dark.png)
- [Recording confirmation with optional settings expanded](screenshots/wilco-capture-consent.png)

These are screenshots of the running implementation with local demo content. They are not generated mockups.

## What changed

Home replaces the statistics banner with a meeting-link and memory composer, one focused follow-up, and recent conversations. Voice and file upload remain secondary actions. Five primary navigation destinations stay visible; More reveals the other tools and command search still reaches them.

Capture carries the pasted link into a compact confirmation, requires recording acknowledgement, and shows success or a recoverable failure. Availability checks do not reset the form. Title and note style remain optional.

Meeting review supports inline task and decision edits, confirmation, and leaving uncertain speakers unnamed. Using a correction to improve future voice matches requires its own opt-in. Transcript, notes, and insights sit behind Full meeting; source and citation links open it automatically. Confidentiality and sharing restrictions remain in the existing API paths.

## Verification

Frontend type checking and a production build passed. Browser verification covered desktop dark and light, 390px mobile layout, composer switching, link handoff, consent gating, optional controls, capture success, failure preserving input, mobile focus trapping and restoration, inline edits, task and decision confirmation, unnamed speakers, detailed meeting disclosure, and reduced-motion styling. The browser reported no uncaught errors.

Reads used saved local demo meetings. Writes were intercepted, including capture requests and review updates, so the checks did not start a real recording, change saved notes, or call the AI generation services. A real two-person Meet and enrolled-voice acceptance test remains separate work.

## Local preview

The isolated frontend runs at `http://localhost:3200`. A local-only proxy on port 3300 forwards to the existing backend on 8000. The shared checkout also contains the new implementation; its existing local frontend can reload those files. Production was not deployed by this checkpoint.

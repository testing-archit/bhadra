---
version: 1
slug: "frontend-src-app-app-dashboard-page-tsx"
primary_target: "frontend/src/app/(app)/dashboard/page.tsx"
related_targets: ["frontend/src/app/(app)/layout.tsx","frontend/src/app/login/page.tsx","frontend/src/app/(app)/meetings/[id]/page.tsx","frontend/src/app/(app)/tasks/page.tsx","frontend/src/app/(app)/memory/page.tsx"]
---

# App shell, Home, Meeting, Tasks, Memory, Sign-in

Scope: the signed-in app shell and its four demo-critical screens plus sign-in. Mode: Operate (sign-in leans Persuade). Audience and job: eng leads and developers between calls, checking what they owe and what was decided. Constraints: light and dark both first-class; existing behaviour, routes and data untouched.

## Direction contract

THESIS: A dark frame holding bright, calm working sheets; the meeting's voice shows up as one signal-yellow waveform. Refuses the AI-app default of purple glow, gradient headlines and glass on every surface.

OWN-WORLD: Ink frame (#0B0B0C) around a pale stone canvas with white sheets (dark theme: graphite sheets). Signal yellow is the single accent: record, ask, the active nav notch, the waveform. Soft pastel tints (peach, lilac, mint, rose, sky) only as chips and status pills. Geist set tight; two-tone headings (ink word, then a grey word); dot-matrix (Doto) numerals only for headline counts. Hairline borders, no glass, no glows outside the hero band.

STORY: The visitor sees their name and what is owed at a glance, clears one item, and trusts where each fact came from.

FIRST VIEWPORT: Ink sidebar left. Home opens on a dark hero band (subtle blue-pink-amber aurora at one edge) with the greeting large, three dot-matrix counts, and the yellow waveform; below it the focus card and recent meetings on the pale canvas. Primary action: "Bring Wilco to a meeting", yellow.

FORM: pinned by the user. seed: none (pinned) "look at frames how cool the ui looks ... we need to replicate in responsible way so that it is cool as well as doesnt distract"

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

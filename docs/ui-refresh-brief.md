# UI refresh handoff

## Current implementation

The Signal Room implementation now spans Home, Meetings, Tasks, Delivery Radar, Decisions, Projects, Memory, Live, the meeting board and setup flows, settings/admin, account recovery, extension setup, and shared links. The sidebar renders normal links instead of a **More** disclosure. Voice lab (`/gnani`) is the focused speech/voice showcase; advanced model details are secondary. `/khata` redirects to `/delivery` while the legacy API stays available for existing integrations. The design contract is [DESIGN.md](../DESIGN.md), with route-family CSS under `frontend/src/app/`.

The interface uses original signal graphics and short CSS motion. Reduced-motion settings suppress those effects. Reuse existing meeting, task, and project API data; do not substitute concept-image numbers. Browser preview and build checks belong to the current branch, while older `wilco-violet-*` screenshots below document earlier passes.

## Context

The user does not like the current Wilco UI and asked for more online UI skills on a separate branch while other agents work. They then asked for an ambitious hackathon interface aimed at software companies, using a shared reel of design-resource libraries as inspiration. See [the signal-room direction](hackathon-ui-direction.md). The earlier teal/orange mascot treatment is a baseline to inspect, not a direction to preserve.

The current design contract is `DESIGN.md`. Use `docs/screenshots/wilco-followthrough-home-desktop.png`, `wilco-followthrough-home-mobile.png`, and the corresponding task, review, Memory, and Live screenshots as evidence. The older `wilco-violet-*` screenshots and `docs/ui-reference.md` document a prior version.

## Original design brief

Review one complete flow before broad restyling: **Home → invite notetaker → live meeting → review notes → act on a task**. The user's dissatisfaction may concern visual taste, task clarity, density, or both; do not claim a cause from screenshots alone. Use `better-interface` and its domain skills against the implementation. The chosen first concept is the signal room; refine it against real Wilco content and preserve the existing consent, access, and error flows.

For each concept, make these decisions explicit:

- What is the first action a returning user sees, and how do they find an active meeting?
- How do live status, notes needing review, and owned tasks rank on Home?
- How do meeting details and a whiteboard fit on smaller screens without hiding source evidence?
- Which typography, colors, spacing, and component shapes make Wilco recognizable without decorative repetition?

The user selected an ambitious direction and `DESIGN.md` now points to the signal-room concept. Keep the existing Next.js, Tailwind, Base UI, and Lucide stack. Verify desktop and mobile screenshots, keyboard focus, 200% zoom, empty/error/loading states, reduced motion, and the production build. A screenshot concept is useful for visual judgment; it is not evidence that interactions work.

## Skill sources added on this branch

- [Interface review pack](https://github.com/jakubkrehel/skills/tree/a72290d140249813898ba8648becf6415abcb059/skills): `better-interface`, `better-accessibility`, `better-layout`, `better-typography`, `better-colors`, `better-writing`, and `better-ui`.
- [Vercel React Best Practices](https://github.com/vercel-labs/agent-skills/tree/1a2c79d4e6c4a2283dc2c614b6538cbe1ed5ca62/skills/react-best-practices): React and Next.js performance checks after meaningful component changes.
- [OpenAI Frontend App Builder](https://github.com/openai/plugins/blob/main/plugins/build-web-apps/skills/frontend-app-builder/SKILL.md) was reviewed as an optional concept-to-browser workflow. It was not vendored because the source repository does not publish a repository-wide license. The existing `frontend-design` skill already covers design direction.

Run `python3 tools/design-skills.py --link-claude` on a clone to verify checksums and make the skill links for Claude Code. Newly installed Codex skills are discovered in the next session.

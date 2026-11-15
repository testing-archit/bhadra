# Wilco design system

## Product and audience

Wilco is meeting intelligence for software companies. The interface helps a team turn an engineering discussion into decisions, owned tasks, project context, and evidence they can revisit. Use incident reviews, release planning, architecture decisions, customer engineering calls, and multilingual team conversations as examples. Demo counts and activity must come from the application, not a visual mockup.

The current design direction is the [Signal Room](docs/hackathon-ui-direction.md). The [concept image](docs/design-references/hackathon-signal-room-concept.png) sets the mood; its names and numbers are illustrative and must not appear as real account data.

## Visual language

- **Frame:** midnight navy shell with precise cyan, violet, and orange signals. Keep page content on the same canvas so a light gutter never surrounds a dark route.
- **Typography:** Geist for interface and headlines, Mukta for Devanagari fallback, Geist Mono for compact source or timing data, Doto only for meaningful numeric emphasis.
- **Surfaces:** use spacing, type size, and one prominent graphic to create hierarchy. A card should hold a real task, decision, meeting, or control; empty cards must direct the next action.
- **Color:** define palette values in route or shared CSS custom properties, then use semantic tokens in components. The app shell lives in `frontend/src/app/hackathon-shell.css`; Home, work pages, meeting intelligence, support tools, public pages, Delivery Radar, and Voice lab each have scoped styles under `frontend/src/app/`.
- **Icons:** Lucide communicates actions and status. The Wilco mascot belongs in brand and voice contexts; it should not decorate every navigation item or work card.

## Navigation

The desktop sidebar is a compact SaaS rail. Every product destination is a normal visible link; there is no **More** disclosure. A distinct **New meeting** action opens the existing capture and import options. The top bar owns command search; the sidebar must not duplicate it. The account menu remains available at the bottom. Admin appears only for admins. On phones, the bottom bar keeps the primary actions close and the menu opens the full destination list.

Primary workflow: **Home → Meetings → Tasks → Delivery Radar → Decisions/Projects → Memory/Live**. Delivery Radar at `/delivery` uses accessible tasks, decisions, and projects. `/khata` redirects there for old bookmarks; the legacy khata API remains for integrations and is not promoted in the product UI.

## Page families

- **Home:** capture action, actual live status, latest notes needing review, owned follow-ups, upcoming calendar, and a user-submitted Memory question. Keep loading, empty, and error states honest.
- **Meetings:** source-backed notes and review. Preserve transcript evidence, access controls, recording consent, processing state, and links to the native FigJam meeting board.
- **Tasks and Delivery Radar:** put the next action and owner first. The Radar derives attention from high-priority or overdue tasks and never invents project health.
- **Decisions and Projects:** show why a choice was made, the source meeting, and related work. Let real activity counts carry the visual hierarchy.
- **Memory and Live:** make question entry immediate. Cite accessible meetings; do not imply a voice or model answered when it did not.
- **Voice lab:** lead with a short visual speech → insight → voice story and working Prisma/Timbre demos. Put advanced model controls in a clear disclosure. Keep Gnani attribution visible and avoid server configuration prose in the main view.
- **Account and utility pages:** use the same typography, surface contrast, and action language as the workspace.

## Motion, accessibility, and trust

Use motion to explain a signal or action. The live listening halo, short header traces, and slow Radar sweep are the main visual moments. Prefer transform and opacity, avoid continuously animating large painted surfaces, and provide `prefers-reduced-motion` fallbacks. Maintain visible focus, keyboard access, readable contrast, and responsive layouts.

Recording consent, speaker uncertainty, confidential meetings, source evidence, and failed saves must remain explicit. A task from a meeting the viewer cannot open must not gain a source link. Demo content is synthetic and labelled. No new feature should make an external API call just to fill a dashboard with decorative data.

## Verification

Check `npm run typecheck` and `npm run build` in `frontend/`. Review desktop and phone browser renders for entry, Home, Meetings, Delivery Radar, Voice lab, and at least one detailed meeting route. Verify empty, loading, error, and reduced-motion states. The repository's ESLint command is currently blocked by TypeScript 7 support in typescript-eslint; this is separate from UI compilation.

Read [docs/coordination.md](docs/coordination.md) before editing or merging shared work. Historical light/violet screenshots and design notes in `docs/` remain records of previous passes, not the current UI contract.

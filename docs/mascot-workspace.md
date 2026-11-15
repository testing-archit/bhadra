# Mascot-led workspace

The user approved the first generated browser mascot and requested a matching site palette and real implementation. Home and Tasks image-model references were generated with ChatGPT's built-in image generator; the exact prompts are retained in `design-references/mascot-ui-prompts.json`. These images guide composition and colour, not runtime content.

## Implemented

- Shared light/dark theme: warm paper, charcoal copy, teal selection, orange key actions and soft pink/lilac/sky-blue bands. Existing routes and components inherit the tokens. Selected sidebar text and key action text use deliberately contrasting foregrounds.
- The approved PNG mascot and its compact face live under `frontend/public/brand/`, with automatic Next image optimisation. Home has a compact mascot welcome band and the existing recording-consent entry point; navigation uses the browser-face mark and a small static mascot cameo when height permits.
- Tasks replaces the rejected grid with one connected Flow surface. All task titles remain visible, with a due-date rail derived from actual tasks, a selected-row cue, and a stable shared action dock. Selection, date filtering and opening menus do not move task rows. Only successful task mutations settle rows with brief transform-only motion.
- Snooze and Reassign use the existing accessible Base UI menu wrapper; Edit opens the existing editor. Done, Snooze, Reassign and Undo use existing API contracts. Failed saves preserve selection, and restricted meetings never get source links. Completed work, List/Board links, exports, bulk tools and teammate filters remain reachable.
- Calendar connection states, recording consent, access rules, actual data and the collaborator's meeting-board implementation are preserved. No backend, connector, bot or AI API feature was added.

## Verification and limits

Frontend TypeScript and production build pass. Twenty-one browser checks passed. Browser validation uses a locally served production build, synthetic task fixtures, and intercepted task writes. It covers selection without layout jumps or writes; real date filtering; keyboard menu access/focus return; failed saves; completion, snooze, reassignment and Undo; clearing a previously absent date; restricted sources; teammate filters; completed/reopened tasks; search/empty states; saved and legacy layout links; 320/390px layouts and menus; Home's consent dialog; loaded mascot assets; dark theme; reduced motion; Undo after the final task; and long text/owner/status handling.

Foreground/background, primary-action, secondary-copy/card and orange-action token pairs each exceed 4.5:1 contrast in light and dark themes. This is a targeted palette check, not a complete WCAG audit. ESLint remains blocked by the existing TypeScript 7 / typescript-eslint incompatibility.

Actual build screenshots use local read-only/demo content and synthetic task fixtures. Generated UI sketches are separate reference images. The preview is at `http://localhost:3200/dashboard` and `/tasks?view=workspace`. This revision is a checked UI-branch checkpoint; it does not deploy the unfinished backend work or replace production automatically.

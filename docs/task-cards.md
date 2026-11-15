# Compact task cards (superseded)

The user subsequently rejected the card presentation. See [mascot-workspace.md](mascot-workspace.md) for the implemented mascot-led Flow. This document records the earlier card checkpoint.

The user rejected the single-task deck as too empty and chose compact task cards from the subsequent options. This replaces the deck default, preserving the existing light/violet design and task APIs.

## Behavior

- Show multiple task titles in a two-column desktop grid and a single mobile column. Keep the full task text, actual due date, project/source and owner initial visible. Priority/status badges wrap when needed.
- Complete a task directly, or expand its title/details arrow for its source and Done / Snooze / Reassign actions. Expand one card at a time. Actions save through existing APIs and support Undo, including after the last task. Failed saves retain the expanded card and expose the server error.
- Search stays visible; scope and alternate layouts are compact selectors; advanced filters start closed. Completed tasks can be reopened. List, Board, editor, exports, bulk operations and follow-up tools remain accessible. Legacy `?view=focus` links open the card layout.
- The Waiting on strip is derived from accessible delegated tasks. Tapping a person scopes the task list to that owner.
- Hide meeting links for `meeting_hidden` tasks. No AI generation, new backend endpoints or dependencies are added.

## Verification

`npm run build` and `npm run typecheck` pass. Sixteen browser checks against the local production build cover card/keyboard selection without writes, rejected saves, busy state, completion/Undo, snooze/Undo for existing and absent dates, reassignment, restricted source links, teammate filtering, completed/reopened tasks, search/empty-state recovery, saved and legacy layout links, mobile actions at 320px, reduced motion, Undo after the last card, and long titles/owners with priority/status badges. All task writes were intercepted against synthetic fixtures; actual saved tasks were not changed.

Screenshots show the initial synthetic fixture state and were visually reviewed:

- `screenshots/wilco-task-cards-desktop.png`
- `screenshots/wilco-task-cards-mobile.png`
- `screenshots/wilco-task-cards-mobile-open.png`
- `screenshots/wilco-task-cards-dark.png`

The preview runs at `http://localhost:3200/tasks?view=workspace`. ESLint remains blocked by the repository's TypeScript 7 / typescript-eslint incompatibility. The card revision is a topic-branch checkpoint for visual feedback; production still runs the previously deployed deck at `25559c0`.

# Task focus deck

Selected by the user on 15 November 2026: Focus deck, with Done, Snooze, and Reassign.

The default Tasks page replaces the four counters, repeated Up next list, persistent filters, and board with one task. Existing task descriptions remain intact. No AI calls or backend changes were added. Previous/next, keyboard activation, and touch swipes browse without writes. Meeting context is collapsed, with restricted meeting links withheld. List and Board links still work; filters, exports, bulk operations, and follow-up tools remain reachable.

Snooze offers Tomorrow / In a week and explicitly moves the calendar due date. It defers the task to the back of the current session rather than concealing it. Reassign offers names already visible in accessible tasks; Someone else opens the existing editor. All three primary actions wait for a successful API response, retain the current task on failure, and offer Undo. Server-computed ownership is reloaded after reassignment.

## Verification

- `npm run typecheck` and `npm run build` passed on the integrated branch, including the collaborator's whiteboard changes and bot chat fix.
- Fifteen browser checks passed against the production build served locally. Task reads/writes used synthetic fixtures; no real tasks were changed. Checks cover keyboard and touch browsing without writes; rejected saves; busy state; completion, snooze, reassignment and Undo; restricted meeting context; filters and empty states; saved List layout; existing Board links; 320px and 390px layouts; reduced motion; dark theme; and Undo after the last task.
- Screenshots use synthetic task fixtures: `screenshots/wilco-task-focus-desktop.png`, `screenshots/wilco-task-focus-mobile.png`, and `screenshots/wilco-task-focus-dark.png`.
- ESLint could not start because the repository's TypeScript 7 version is unsupported by its installed typescript-eslint. Dependency versions were preserved; typecheck and production build succeeded.

The browser walkthrough verifies frontend behavior and API payloads, not new backend permissions or a live authenticated production session.

# Home: follow-ups and review

The user chose finishing follow-ups and reviewing notes as Home’s primary job. This revision makes useful work visible before a large calendar connection state can push it below the fold. It retains the approved mascot, warm paper palette and teal/orange controls.

## What changed

- The compact latest-meeting band shows the actual title and details needing confirmation. Review notes opens the existing guided review; unavailable speaker or meeting data never claims everything is confirmed. Invite Wilco still opens the recording-consent dialog.
- Four owned follow-ups are ordered by actual due-date urgency. Complete waits for the server before changing the list or progress; Undo restores the previous status. Keyboard focus moves to Undo after completion. A restricted meeting is labelled Shared task without exposing its source.
- Progress counts completed and open owned tasks returned by the existing API. It excludes delegated tasks, keeps the denominator stable when one is completed, and explicitly describes its scope. It is not a weekly target or a claim of time saved.
- Calendar connection, empty and error states take a small panel. A linked calendar shows the next two live/upcoming events; the full calendar retains its controls.
- A concise question field and two meeting-memory prompts hand off to the existing Memory flow only after user action. Nothing generates an answer on Home load. Recent notes use short rows with real titles, dates and processing states.

## Behavioural rationale and limits

[Fogg’s model](https://www.behaviormodel.org/home) connects a prompt with the ability and motivation to act. Applying that framework here suggests putting a relevant next action beside the meeting that created it, and reducing the effort to complete or review it. This is a design inference, not a demonstrated Wilco retention result.

[Harkin et al.’s experimental meta-analysis](https://www.apa.org/pubs/journals/releases/bul-bul0000025.pdf) found that interventions supporting progress monitoring improved goal attainment on average. That supports trying honest completion feedback. It does not establish that this particular progress bar will improve retention, or that whitespace itself causes boredom. No streaks, invented social activity or arbitrary targets were added.

A useful return loop to evaluate is: meeting finishes → open notes → confirm details → finish a follow-up → return for the next meeting or answer. Proposed outcome measures are next-day return among users with a ready meeting, the proportion who confirm a detail, and seven-day completion of follow-ups created in a fixed meeting cohort. Compare similar active teams and meeting volumes; monitor Undo/reopen rates to catch accidental completion. These are a measurement plan, not installed analytics or measured improvements.

## Validation

Production build and TypeScript checks pass. Twenty Home browser checks pass, covering owned/delegated counts; restricted sources; failed saves; save/Undo and keyboard focus recovery; completion of the last task; desktop action placement; consent; explicit memory submission without refresh replay or automatic requests; suggested questions; waiting/task-editor links; compact/full calendars and recovery; missing review data; failed task/meeting reads; zero tasks; long text at 320/390px; dark theme and reduced motion. Browser checks and screenshots use local demo meeting snapshots and synthetic task fixtures; all task writes and memory answers are intercepted. No real recording is started, saved task is changed, or AI request is billed by these checks.

The checked UI is served at `http://localhost:3200/dashboard` from the isolated UI worktree. It is a topic-branch preview, not a production release. ESLint remains blocked by the existing TypeScript 7 / typescript-eslint compatibility issue.

Actual screenshots: `screenshots/wilco-followthrough-home-desktop.png`, `screenshots/wilco-followthrough-home-mobile.png`, and `screenshots/wilco-followthrough-home-dark.png`.

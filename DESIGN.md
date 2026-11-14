# Wilco design system

Wilco helps people stay in the conversation and leave with clear next steps. The reference video supplied on 15 November 2026 informs the dark canvas, blue and pink perimeter light, compact input, and generous spacing. Colour draws attention to the entrance; work stays calm.

## Visual direction

- Home has one composer for joining a meeting or asking about past meetings. A focused follow-up and recent conversations sit underneath. Do not add a statistics banner or competing promotional cards.
- Atmosphere is static and scoped to Home. Keep it away from task text, transcripts, forms, and meeting review. The light theme uses the same structure with a pale, cool canvas.
- Surfaces use a quiet border and restrained radius. The composer and focused review are distinct surfaces; recent meetings are simple rows. Avoid nested cards.
- Geist carries interface and display text. Mukta provides Devanagari fallback. Keep display text compact enough that the next action remains visible. Doto remains available for existing call sites but Home does not use decorative counters.

## Theme tokens

All component colours come from `frontend/src/app/globals.css`. Define palette changes there, never as hard-coded component colours.

| Role | Tokens |
| --- | --- |
| Canvas and copy | `--background`, `--foreground` |
| Working surfaces | `--card`, `--card-foreground`, `--border` |
| Secondary text | `--muted-foreground` |
| Primary action | `--primary`, `--primary-foreground` |
| Cool blue brand accent | `--marigold`, `--marigold-foreground` (legacy token names retained for existing consumers) |
| Home perimeter light | `--aurora-a` (cobalt), `--aurora-b` (orchid) |
| Recording, errors, success | `--destructive`, `--warning`, `--success` |
| Small meeting markers | `--tint-sky`, `--tint-lilac`, `--tint-peach` and their foregrounds |

The dark canvas is `oklch(0.135 0.012 270)`; the light canvas is `oklch(0.982 0.004 260)`. The cool blue accent is `oklch(0.8 0.12 260)`. Keep colour out of dense body copy.

## Primary journeys

**Home:** paste a Meet or Teams link, continue to recording consent, then invite Wilco. Asking past meetings is a separate composer tab. Recording in person and uploading remain small secondary links. A live capture shows its real status; no decorative waveform implies that recording has started.

**Meeting review:** one task, decision, or uncertain speaker at a time. Confirm or edit inline. Open source evidence when needed. The full transcript, notes, and insights sit behind the Full meeting disclosure; citation deep links open it automatically. A skipped speaker remains unnamed. Saving a speaker name and opting into future voice learning are separate choices.

**Navigation:** Home, Meetings, Tasks, Memory, and Talk to Wilco are primary. More reveals the remaining tools. All pages remain available in command search. Mobile navigation uses the existing Base UI dialog for focus management and Escape dismissal.

**Capture:** keep one link field, an explicit recording acknowledgement, and optional title/style controls. Show a clear success state, queue state, or recoverable error. Loading notetaker status must not reset entered text or consent.

## Copy and accessibility

Use short, concrete labels that describe the next action. Keep consent, access restrictions, errors, and uncertain identification explicit. Avoid repeated explanations and decorative labels. Label every input and icon-only control, associate field errors, show keyboard focus, and preserve contrast in both themes.

## Motion

Use short transitions for direct interaction feedback. Do not animate the Home atmosphere or run background particle loops. Animate transform and opacity where possible, respect reduced motion, and keep blur static and confined to existing overlay behaviour. Do not add an animation library solely for decoration.

## Implementation

Reuse the existing Base UI / shadcn primitives, Lucide icons, authentication, capture queue, and meeting APIs. `HomeComposer` owns the Home input. `GuidedReview` owns focused review. Theme styles belong in the shared stylesheet. See `docs/design-skills.md` for installed skills and `docs/coordination.md` before editing shared files.

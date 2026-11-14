# Wilco design system: "night glow"

Wilco is voice-first meeting memory for Indian teams. The look follows a pinned reference: a dark sky lit by soft colour, frosted glass surfaces, and one big prompt you can type into or speak to. It's blended with Wilco's own identity: neel indigo, a genda-marigold accent, Devanagari-ready type, and Hinglish copy.

## Principles

- **Voice is the way in.** The marigold mic is the one bright, always-findable action. Don't give anything else marigold's weight.
- **Bold at the door, calm in the room.** Home's hero and the sign-in page carry the glow, the gradient headline and the big glass prompt. Working screens (meetings, tasks, decisions, settings) stay restrained: familiar controls, dense lists, no decoration.
- **Glass is a material, not a garnish.** Only floating surfaces are frosted: cards, the sidebar, menus, the prompt. The page itself is never glass.
- **No eyebrows.** No kicker or label line above a heading; the heading carries its own weight.

## Colour (tokens in `frontend/src/app/globals.css`)

Components use tokens only, never raw hex values.

| Role | Dark (default) | Light |
|---|---|---|
| Page | night `#0E0C1F` (`--background`) | lavender white |
| Glows behind the page | neel-violet, gulabi pink, genda (`--glow-a/b/c`) | the same in pastel |
| Text | near-white | deep indigo ink |
| Primary (links, selection, focus) | violet `#8B7CFF` | neel `#5B4CF0` |
| Accent: record and ask actions only | genda marigold `#F0A020` (`--marigold`) | same |
| Success / destructive | mehendi green / sindoor red | same |
| Surfaces | white at 5% over the glow, 22px blur | white at 62% over the glow |

- **Glows:** fixed radial gradients drawn by `body::before`: top centre, right edge, bottom left.
- **Dark first:** the app opens in dark mode, with light and system as choices. The pinned reference is dark, and the light theme is a full equal, not an afterthought.
- **Browser surfaces:** selection, the caret (marigold), scrollbars and checkbox/radio accents are themed. Numbers use tabular figures.

## Type

- **Baloo 2** for headings (`font-heading`; h1–h3 by default) and **Mukta** for body text. Both are by Ek Type and both carry Devanagari, so Hindi and Hinglish render in the same family as English.
- **Hero headlines:** up to 6xl, tight leading, `text-balance`. The person's name, or the key word, takes the `.text-glow` sweep (white → violet → gulabi → genda).
- **Gradient text** is reserved for one phrase per hero. Never use it in working screens.

## Components

- **`PromptHero`** (Home): one glass prompt box.
  - It contains a textarea, a "Capture a meeting" chip and a "Record in person" chip. Below `sm` the chips show icons only, with aria-labels.
  - On the right sit the marigold mic (`VoiceAskButton`) and a round send button.
  - Hinglish example questions sit below as glass chips.
  - Typed questions open `/memory?q=`. Spoken ones add `&voice=1`, so the answer is read aloud.
- **`VoiceAskButton`:** marigold rounded square. While recording it turns red with a pulse and a timer, then shows "Listening" while Gnani Prisma transcribes.
- **`SpeakButton`:** "Listen" / "Stop", reads text aloud with Gnani Timbre. Compact under chat answers, outline on the meeting summary. One voice plays at a time.
- **`Card`:** 2xl radius, glass (`bg-card` with backdrop blur), and a 1px ring. Never nest cards.
- **Sidebar:** glass. The active item has a marigold bar on its left edge, and "New meeting" is a marigold pill.
- **Brand:** `BrandMark` is a speech bubble with a marigold bindi on neel, in `components/brand.tsx`. On sign-in the Devanagari wordmark चर्चा takes the gradient sweep.

## Motion

- Transitions are 150–250 ms and only show state changes: recording pulse, loading spinners, hover colour.
- There's no page-load choreography in the app.

## Copy

- Sentence case and plain verbs. Hinglish where users would speak it: "Bolo", "Kuch bhi poocho…", "Wilco sun raha hai".
- Say "charcha" for a conversation: "New meeting", "Record a meeting".

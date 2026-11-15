# Wilco: 60-second demo, shot plan

**Goal:** the best 60-second demo (Gnani "Demo Day Drop" award). One Hinglish sentence follows through the whole film: it's spoken in a call, then becomes a whiteboard, then a task, then a cited answer, then shows how Wilco fits the team's tools.

**What a viewer should remember:** "You talk in Hinglish; Wilco does the follow-up."

**Format:** exactly 60.0 s (1,800 frames at 30 fps), 1920×1080, with voice and a quiet music bed that ducks under speech.

## Material we already have (all real, all 1080p)

| Source | Where it comes from in `final/wilco-recording-1080p.mp4` |
|---|---|
| Mock call: Priya's line, Arjun, the board request, the whiteboard building in three versions, Wilco's recap, Wilco's avatar tile | 0:00–0:39 |
| Live app, Home | 0:39–0:47 |
| Meeting debrief | 0:47–0:55 |
| Tasks | 0:55–1:00 |
| Memory: question typed, then the real cited answer | 1:00–1:18 |
| Talk to Wilco | 1:18–1:26 |
| Integrations grid | 1:26–1:42 |

## The cut (dense version: 16 features in 60 s)

| Time | Beat | Picture (real footage unless noted) | Sound |
|---|---|---|---|
| 0:00–0:03 | 1. Joins the call and understands Hinglish | Mock call; Priya's caption with a **FRIDAY** punch-in | Priya: "Arjun, onboarding flow… Friday tak. Pehle OTP, phir KYC." |
| 0:03–0:10 | 2. Live whiteboard in Meet · 3. Wilco's avatar | "Wilco, board pe… flow bana do", then the board builds in three versions; the avatar tile speaks | Priya's request, then Wilco: "Sure, sharing the board now." |
| 0:10–0:15 | 4. Spoken recap in the call | Wilco's recap caption | Wilco: "Arjun owns… due Friday. OTP before KYC." |
| 0:15–0:21 | 5. Debrief with moments · 6. Tasks with owners | Meeting debrief, then Tasks (real app) | Narrator: "Every decision and task, linked to the moment it was said." |
| 0:21–0:30 | 7. Ask your meetings, with sources | Memory: question, then cited answer (wait shortened, labelled) | Narrator: "Ask later. Wilco answers with its sources." |
| 0:30–0:34 | 8. Talk to Wilco in 11 languages | Talk to Wilco page | Narrator: "Or just talk to it, in eleven Indian languages." |
| 0:34–0:48 | **Feature rush:** 7 beats of 2 s each, a big verb title plus the real screen where we have one | 9. Voice → Jira ticket · 10. Spoken stand-ups and pre-call briefs · 11. Live call translation · 12. Hear the original decision quote · 13. AI stand-in in your own consented voice · 14. Phone calls and WhatsApp voice notes → recap · 15. Delivery Radar (real screen) | Narrator over the beat: "Voice to Jira. Spoken stand-ups. Live translation. The original quote. Your stand-in, in your voice. Phone-call recaps." |
| 0:48–0:55 | 16. Already works with your stack | Integrations grid: Meet, Teams, Calendar, Jira, FigJam, Gmail, WhatsApp, Sheets, Claude, Gnani | Narrator: "And it already works with Meet, Teams, Calendar, Jira and more." |
| 0:55–1:00 | End card | Mascot, "Wilco. Your meeting, still useful.", link, "Built on Gnani Prisma + Timbre", hashtags, voice disclosure | Narrator: "Wilco. Your meeting, still useful." |

**Duration check:** 3 + 7 + 5 + 6 + 9 + 4 + 14 + 7 + 5 = **60 s**.

The feature-rush beats 9–14 have no recorded screens. Each one is a typographic card using its real example phrase (for instance "Wilco, Jira ticket bana do: webhook retry bug, assign Vedant"). Each is labelled as a feature card, never drawn as fake UI.

## Rules

- Every product screen is real footage. The only mock is the call itself, and it says so on screen.
- Nothing is sped up. Waits are cut and labelled "wait shortened".
- Claims stay inside what the code does. Zoom and Webex get briefs only, so they're left out of the 60 s. Native FigJam isn't claimed; the board is Wilco's own renderer.
- The voices are Gemini TTS, disclosed on the end card and in the post.
- Title-safe margins; text at least 26 px after any push-in; no text near the edges.
- Check before delivering: exactly 60.000 s, no audio gap longer than 1.5 s, and the frames looked at.

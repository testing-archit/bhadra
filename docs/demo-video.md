# Wilco demo video: Gnani AI Internship Challenge

> **Current deliverables (updated 15 Nov 2026), in `video/final/`:**
> - `wilco-demo-60s.mp4`: the 60-second, 16-feature cut (plan in `video/PLAN-60s.md`, source in `video/demo60/`)
> - `wilco-recording-1080p.mp4`: the screen recording of a mock call (live whiteboard and avatar) plus the live app, with an integrations scene at the end
> - `wilco-full-1080p.mp4`: the recording followed by both motion videos
>
> All voices are Gemini TTS stand-ins, which the videos disclose. The sections below describe the first motion video (`video/wilco-demo/`).

The demo video for the **Great Indian AI Internship Challenge** (https://www.gnani.ai/internship). Entries close **15 Nov 2026, 18:00 IST**.

- **File:** `video/wilco-gnani-demo.mp4` (50 s, 1920×1080, 30 fps, H.264 + AAC, 8.9 MB)
- **Source project:** `video/wilco-demo/` (HyperFrames: HTML rendered to video)
- **Award it targets:** "Demo Day Drop" (best 60-second demo). The video also supports Mixed Vibes, Real Deal and Main Character.

## What the challenge asks of the video

| Rule (gnani.ai/internship) | How the video meets it |
|---|---|
| Show the app working and explain it | Real Wilco screens: Home, Tasks, Talk to Wilco |
| Name the Gnani AI technology used | On-screen tags and a closing card: Prisma v3, Timbre v2.5 + v3, vachana-vc-v1 |
| Synthetic data only | Seeded demo data only. No real phone numbers, IDs or calls. |
| No misleading demos | The narration is Gemini TTS, so the post must say so (see below). Every voice inside Wilco is Gnani. |
| Post on LinkedIn or X, tag Gnani AI, add #GreatIndianAIInternshipChallenge #GnaniAI | The hashtags are on the end card. The tag goes in the post itself. |
| Nominate the post link in the form | https://forms.cloud.microsoft/r/dfFShbp7W7 |

## Scenes and narration

| Time | Scene | On screen | Narration (Gemini TTS) |
|---|---|---|---|
| 0–5 s | Hook | Hinglish call lines pop up as speech bubbles on the mascot gradient, then fall away | "Every Indian team call sounds like this." |
| 5–10 s | Tension | "Call khatam. Kaun karega? **Kab tak?**" | "Then the call ends. Kaun karega? Kab tak? Nobody knows." |
| 10–15 s | Reveal | The Wilco mascot walks in. "Wilco: your meeting teammate that speaks Hinglish." | "Meet Wilco. Your meeting teammate that speaks Hinglish." |
| 15–21 s | It joins your call | Real Home screen, punch-in on **Invite Wilco**. Tag: Records & listens · Gnani Prisma v3. | "Invite Wilco to your Google Meet. It listens with Gnani Prisma v3." |
| 21–29 s | Voice → task | Waveform, then the line "Wilco, Vedant ko login bug Friday tak fix karna hai, task bana do". Tag: Prisma v3 codemix. Real Tasks page slides in. | "Just say it in Hinglish, and it becomes a real task, with an owner and a due date." |
| 29–37 s | Talk to Wilco | Real Talk to Wilco screen ("Wilco is speaking"). Tag: Gnani Timbre v2.5 + v3. 11 language chips. | "Ask out loud. Wilco talks back in a Gnani Timbre voice, in eleven Indian languages." |
| 37–44 s | Built on Gnani | "Every voice in Wilco is **Gnani**", with cards for Prisma v3 (speech-to-text), Timbre v2.5 + v3 (text-to-speech) and vachana-vc-v1 (voice cloning) | "Every voice in Wilco is Gnani. Prisma, Timbre, and voice cloning." |
| 44–50 s | End card | Mascot drops in. "Wilco: Meetings that turn into work". Try it: 34-58-54-115.sslip.io. Built on Gnani AI, plus the hashtags. | "Wilco. Meetings that turn into work." |

## Assets

| Asset | Source |
|---|---|
| `assets/wilco-mascot-v1.png` | `frontend/public/brand/wilco-mascot-v1.png` |
| `assets/wilco-mascot-home-desktop.png` | `docs/screenshots/wilco-mascot-home-desktop.png` |
| `assets/wilco-task-cards-desktop.png` | `docs/screenshots/wilco-task-cards-desktop.png` |
| `assets/wilco-live-speaking.png` | `docs/screenshots/wilco-live-speaking.png` |
| `assets/vo/s1.wav` … `s8.wav` | Gemini TTS, voice "Puck". s1–s7: `gemini-2.5-flash-preview-tts`. s8: `gemini-2.5-pro-preview-tts` (Flash hit a rate limit). |

Look: Poppins type; the mascot's pink → violet → blue gradient; marigold `#ff9419` as the accent; teal `#17666e`; ink outlines with hard offset shadows. There's no background music.

## Post text (LinkedIn / X)

> Indian team calls happen in two languages at once, and the owners and deadlines get lost. We built **Wilco**, a voice-first meeting teammate. It joins your Meet call, turns Hinglish into tasks and decisions, and talks back in 11 Indian languages.
>
> Built on @Gnani AI: Prisma v3 for code-mixed speech-to-text, Timbre v2.5 + v3 for speech, and vachana-vc-v1 for opt-in voice cloning.
>
> Try it: https://34-58-54-115.sslip.io
>
> (Narration: Gemini TTS. Every voice inside Wilco is Gnani Timbre.)
>
> #GreatIndianAIInternshipChallenge #GnaniAI

Tag the **Gnani AI** company page in the post. The written explanation for the form is in `docs/submission.md`.

## Rebuild or edit

```bash
cd video/wilco-demo
npx hyperframes check                                  # lint + layout
npx hyperframes snapshot --at 2,7,12,18,23,33,40,47    # look at frames
npx hyperframes render --output ../wilco-gnani-demo.mp4  # ~30 s
```

- **Copy and timing:** `video/wilco-demo/index.html`. Each scene is a `.scene.clip` with `data-start`/`data-duration`; the GSAP tweens are at the bottom of the file.
- **Narration:** the `<audio id="vo-sN">` tags near the end of `#root`. To regenerate a line, call Gemini TTS: POST `generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent` with `responseModalities: ["AUDIO"]`. The response is 24 kHz s16le mono PCM; convert it with `ffmpeg -f s16le -ar 24000 -ac 1 -i in.pcm out.wav`.
- **Better narration later:** re-voice with Gnani Timbre v2.5 (`hi-en`) through `backend/app/services/tts_service.py` on the server, which holds the Gnani key. Then the whole film is Gnani-voiced and the disclosure line can go.

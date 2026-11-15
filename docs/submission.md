# Gnani AI Internship Challenge: submission text

Draft for the form at https://forms.cloud.microsoft/r/dfFShbp7W7 (deadline 15 Nov 2026, 18:00 IST). Edit the team section before submitting.

**Live app:** https://34-58-54-115.sslip.io (tap "Try the demo, no sign-up").

## One line

Wilco is a voice-first meeting teammate for Indian software teams. It joins your calls, turns Hinglish, Tanglish and Benglish discussion into tasks, decisions and delivery status, and talks back in your language. Every voice in it is a Gnani model.

## What we built (written explanation)

Indian software teams run on calls held in two languages at once: a stand-up in Hinglish, a client call in Tanglish, a design review in Benglish. Decisions and owners get lost in that mix. Wilco turns the speech into tasks, decisions and delivery status, and speaks back in each person's language.

- **Wilco in your calls.** It joins Google Meet (or Teams), records, and answers "Wilco, …" said aloud or typed in chat. You can ask for a recap in Tamil, draw a flow on a shared FigJam board, add a task, or pause recording for a sensitive part. It replies in the call in a Gnani Timbre voice.
- **AI stand-in for an absent teammate.** Someone who can't attend records 20 seconds of their voice once, with explicit consent, and briefs their stand-in. In the call, Wilco plays their update in an AI copy of their voice. It answers "Wilco, ask Vedant, is KYC done?" only from their briefing, always says it's AI, never commits them to anything, and reports every question back to them.
- **Tasks by voice.** Say "Vedant ko login bug Friday tak fix karna hai, task bana do" to Wilco and it becomes a real task with an owner and due date, on the Tasks page and Delivery Radar.
- **Talk to Wilco.** A hands-free spoken conversation about your meetings ("Why did we roll back the auth release?"), in 11 Indian languages, which you can interrupt.
- **Delivery Radar.** Follow-ups, urgent work, decisions and project activity from every call, in one live view.
- **Notes that hold up, in your language.** Every meeting gets a summary, tasks with owners, decisions with reasons, and quotes from the transcript. You can hear the summary in 11 Indian languages and send it on WhatsApp.
- **Phone calls and voice notes.** Upload a noisy phone call or a WhatsApp voice note and get the recap, read back to you.

## Gnani AI models and APIs used

| Model / API | Where Wilco uses it |
|---|---|
| **Prisma v3.0** (speech-to-text, `codemix`, Auto-LID) | Every meeting transcript, spoken questions and voice tasks in Talk to Wilco, phone calls and voice notes, the live try-it on `/gnani` |
| **Timbre v2.5** (`hi-en`, fast Hinglish/English voice) | Wilco's voice in Meet calls, spoken replies in Talk to Wilco |
| **Timbre v3.0** (multilingual) | Tamil, Telugu, Kannada, Malayalam, Marathi, Bengali, Gujarati and Punjabi speech, chosen from the answer's script; notes read aloud in 11 languages and sent as WhatsApp voice notes |
| **Timbre voice cloning** (`vachana-vc-v1`, voice-clone embeddings API) | The opt-in AI stand-in: an absent teammate's update and answers in their own consented voice |
| **Evon v3.3** (open weights) | Optional answer model for Talk to Wilco when the team hosts it (`EVON_URL`, any OpenAI-compatible server) |

Warp (speech-to-speech) has no public API yet, so Talk to Wilco runs the same loop as three steps: Prisma, an answer model, then Timbre.

**Try every model live:** sign in, or use the demo, then open **Built on Gnani** (`/gnani`).

## Categories we're entering

- **Mixed Vibes:** Hinglish, Tanglish and Benglish engineering calls, voice tasks and spoken answers. Prisma Auto-LID and `codemix` handle switching mid-sentence.
- **Real Deal:** owners and decisions no longer lost from code-mixed calls; absent teammates still contribute through their AI stand-in; follow-ups tracked on Delivery Radar.
- **Jugaad Genius:** an AI stand-in that attends the meeting for you in your own cloned voice, transparently.
- **Main Character:** notes, replies and reminders in 11 Indian languages, in their own scripts.
- **Noise Canceller:** phone-call and WhatsApp voice-note recaps (8 kHz telephony audio).

## Team (edit before submitting)

- **Archit:** … (fill in your contribution)
- **Vedant:** … (fill in your contribution)

## Responsible use

- Voice cloning is opt-in, limited to your own voice and deletable anytime. Only the voice embedding is stored, encrypted. The sample recording is never stored.
- The stand-in always announces that it's AI and never agrees to work on anyone's behalf.
- Recording consent is required, and anyone in a call can pause the recording by voice.
- All demo data is synthetic.

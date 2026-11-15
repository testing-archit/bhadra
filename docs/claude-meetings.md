# Claude Meetings, and what Charcha built around it

Source: https://claude.com/resources/articles/claude-meetings (Anthropic, "Introducing Claude Meetings", 12 Nov 2026, beta).
This file has two parts:
- **What we built:** each Claude Meetings capability mapped to Charcha's implementation, with the code and its test status.
- **Research report:** the full deep research done on 15 Nov 2026.

Keep this file updated when a stage changes.

## What Claude Meetings is, in short

- **What it is:** Claude joins a **Google Meet** call as a visible participant. It's for Team and Enterprise plans, in beta from 12 Nov 2026.
- **During the call:** it answers questions you type or say ("Claude, ...") in the Meet chat. It uses each person's connected tools, after asking their permission. It also builds docs, whiteboards and slides live.
- **After the call:** a meeting page in claude.ai holds the notes, action items, the transcript and those artifacts, and invitees get a recap email.
- **Privacy:**
  - It joins only internal meetings by default, and leaves when an outsider joins.
  - It stores no audio.
  - Admins have three switches: the feature itself, external guests, and members' connectors in meetings.
- **Gaps:**
  - No public API.
  - Nothing documented on Hindi or Hinglish.
  - Google Meet only.

## What Charcha built (status 15 Nov 2026)

| Claude Meetings capability | Charcha's version | Where in the code | Status |
|---|---|---|---|
| Joins the call as a bot | Notetaker joins Meet (and Teams by link) as a signed-in Google account (`auth.json`), from Capture a meeting, a linked calendar or an invite | `backend/bot/meeting_session.py`, `capture_service.py` | ✅ Live-tested 15 Nov |
| Announces itself in chat | Join notice: who invited it, that it records, "charcha please leave", where the notes go | `backend/bot/meet_chat.py` (`join_notice`, `send`) | ✅ Live-tested 15 Nov |
| Answers questions in the call | "Charcha, ..." in Meet chat is answered from **this call's captions only**. No company memory, because guests can ask too. Replies are plain text in the question's language | `meet_chat.ChatWatcher`, `POST /api/bot/live-answer`, `app/services/live_assist.py` | ✅ Live-tested 15 Nov |
| Recap before the call ends | "Charcha recap" gives key points, then decisions, then action items | `live_assist.SYSTEM_PROMPT` | ✅ Live-tested 15 Nov |
| Uses connected tools mid-call | "Charcha, add task: X by Friday" is parsed into owner, task and deadline, held on the visit, and becomes a real task (origin `live`) when the notes are created | `POST /api/bot/live-task`, `capture_requests.live_tasks`, `bot._attach_live_tasks` | ✅ Live-tested 15 Nov (held task stored) |
| Notes, transcript and recap after the call | Meeting page: summary, tasks, decisions and risks with evidence quotes, the transcript, and a follow-up draft | existing pipeline (`insight_service`, `meetings.py`) | ✅ Existing |
| Ask about past meetings | Company memory chat with line citations. It falls back to the 10 newest readable meetings when the vector store is missing | `routes/chat.py`, `memory_retriever.py` | ✅ |
| (Not in Claude) Voice in, voice out | Ask by voice (Gnani Prisma), answers read aloud (Gnani Timbre, Hinglish `hi-en`) | `voice-ask-button.tsx`, `speak-button.tsx`, `POST /api/tts` | ✅ |
| (Not in Claude) In-person conversations | `/record` in-person recorder, code-mixed speech-to-text | existing | ✅ |
| Claude reads your data via connectors | Charcha **is** an MCP server for Claude: `search_meetings`, `get_meeting`, `list_my_tasks`, `list_decisions`, `ask_memory`, `create_task`. Token from Settings → Connect Claude | `app/mcp_server.py`, `/api/mcp` | ✅ Tested over HTTP |
| (Not in Claude) **Charcha Live** | Hands-free spoken conversation about your meetings, like Gemini Live. Voice detection in the browser, interrupt to cut it off, replies in the detected language (11 languages) | `components/live-session.tsx`, `POST /api/live/turn`, `live_conversation.py` | ✅ Tested end to end (Hinglish 4.4 s, Tamil 10 s per turn) |
| Live docs, whiteboards, slides | "Wilco, draw …" edits a live meeting board or native shapes in a paired FigJam file (move, rename, connect, undo by voice). Docs and slides not built | `bot/board_intent.py`, `app/services/meeting_agent.py`, `board_service.py`, `figjam_service.py`, `integrations/figjam/` | ✅ Deployed; real-call FigJam acceptance pending |
| (Not in Claude) Off the record | "Wilco, pause recording" / "resume": audio muted, words said meanwhile never reach notes | `meeting_session.set_recording_paused`, `CaptionLog.private` | ✅ Unit-tested |
| (Not in Claude) AI stand-in for an absent teammate | Gives their update and answers questions put to them ("Wilco, ask Vedant …") in their consented cloned voice, from their briefing only, disclosed as AI; questions reported back | `standin_service.py`, `bot.py` standins, `meeting_session.answer_as_standin` | ✅ Tested; real-call pending |
| (Not in Claude) Absent teammate's voice update | Typed update spoken in the call in the author's consented cloned voice (Gnani Timbre VC), disclosed as AI | `routes/gnani_lab.py`, `bot.py` voice-updates, `meeting_session.play_voice_updates` | ✅ Tested; real-call pending |
| (Not in Claude) Voice khata for shops | Spoken udhaar/payment lines (any Indian language) become a ledger; reminders in the customer's language as WhatsApp text or Timbre voice note | `routes/khata.py`, `khata_service.py`, `/khata` | ✅ Tested |
| (Not in Claude) Listen in your language | Meeting summary translated and read in 11 Indian languages | `routes/tts.py /translated`, `listen-in-language.tsx` | ✅ |
| (Not in Claude) Built on Gnani lab | Live try-its for Prisma, Timbre v2.5/v3, voice cloning, Evon (when hosted) | `/gnani`, `routes/gnani_lab.py`, `evon_service.py` | ✅ |
| Speaks in the call | The notetaker says its answers aloud: Timbre audio goes into a virtual microphone, unmuting only while it speaks. Questions said aloud ("Charcha, …") are picked up from captions | `meeting_session.speak`, `spoken_questions`, `POST /api/bot/speak` | ✅ Deployed, not yet heard in a real call |

## How to try each piece

See `docs/testing-guide.md`.

---

## Research report: Charcha answers Claude Meetings in Hinglish

Anthropic's Claude Meetings, a beta launched on 12 Nov 2026, makes Claude a **visible participant in Google Meet calls**. It answers spoken or typed questions in the Meet chat, uses each person's connected tools once they approve, builds docs, whiteboards and slides while people watch, and files notes, action items and a transcript on a per-meeting page in claude.ai. It saves no audio ([claude.com](https://claude.com/resources/articles/claude-meetings); [Help Center](https://support.claude.com/en/articles/18325154)). It is limited to **Google Meet and Team/Enterprise plans**, and its sources say nothing about which languages it transcribes. Charcha already matches or beats it on everything that happens after a call: calendar auto-join, Teams by link, in-person recording, Gnani Prisma code-mixed STT, briefs, Jira sync, and a finer-grained privacy layer. What Charcha lacks is anything live during the call, and it has no voice of its own. With about 17 hours left before the Gnani AI "Great Indian AI Internship Challenge" closes at 18:00 IST today ([Gnani](https://www.gnani.ai/internship)), the right move is not to chase Claude's live features. Do three things in order. First, add the missing Gemini key so the notes stop being placeholders. Second, add one Gnani-centric feature: spoken answers and read-back through Timbre v2.5 TTS, so the demo runs Gnani in, Gnani out. Third, post a tight 60-second video early, because shortlisting depends largely on verified engagement with the post. The longer-horizon items (an MCP connector, WhatsApp voice follow-ups, a live in-call co-pilot, and the optional Scaler round on 27–29 Nov) all reuse that same voice layer.

## Claude Meetings is a live co-worker, not a notetaker

Anthropic frames the product around **doing work during the call** rather than summarising it afterwards. The launch article follows a team planning a customer event. Claude drafts a plan that invitees edit live. When budget comes up, it asks permission before using a connected tool to look up last year's event cost, then posts the comparison in chat. It puts the timeline on a whiteboard next to the doc and sends a recap when asked. After the call, the notes, action items, plan and whiteboard all sit on the meeting's page in claude.ai, where people can query them later in ordinary chat ([claude.com](https://claude.com/resources/articles/claude-meetings)). The release notes list **docs, whiteboards and slides** as the artifacts it can build in a call ([Release notes](https://support.claude.com/en/articles/12138966-release-notes)). Whiteboards are a separate beta that can group ideas, add owners and dates, and export to Lucid, Miro or Vani by Zoho ([Sheets/Whiteboards/Data](https://claude.com/resources/articles/sheets-whiteboards-data)).

The workflow runs in three stages. **Before the call**, an org owner enables Google Calendar. A user then connects their calendar at claude.ai/meetings and either clicks "Add Claude" on an event or turns on auto-join for all meetings, or for all except one-on-ones. **During the call**, people say "Claude…" or type in Meet chat. Answers come back in writing by default. Claude's tile shows its current state, and it can be paused, removed, or kept for up to 8 hours. **After the call**, internal invitees get a recap email that links to the page holding the notes, transcript and artifacts ([Help Center](https://support.claude.com/en/articles/18325154)). Claude makes its own transcript as a bot participant. Third-party notetakers (Gong, Attention, Granola, Fireflies.ai, Otter, Plaud) are partners that will receive transcripts "soon", not data sources ([claude.com](https://claude.com/resources/articles/claude-meetings)).

The governance model is coarse but explicit. Tool use needs each person's own permission: the first request asks, and a yes carries forward. For spoken requests, Claude asks who is speaking every time. Anything it posts in Meet chat is visible to everyone on the call, while the meeting-page chat stays internal. Admins control three switches: the feature itself, external guests, and members' connectors in meetings. If another company's notetaker bot joins, Claude treats it as an outsider ([Help Center](https://support.claude.com/en/articles/18325154)). On pricing, notes, transcripts and answers that don't use tools are free during the beta, artifacts are free until **10 Feb 2027**, and tool calls count against plan usage. Organisations with zero data retention, HIPAA-ready setups or customer-managed keys are excluded ([claude.com](https://claude.com/resources/articles/claude-meetings)). There is no public API, so a third party like Charcha can complement Claude Meetings or compete with it, but cannot build on top of it. The sources describe no pre-meeting brief, no tracker export other than through connectors, and nothing about Hindi or code-mixed speech.

## Meeting assistants are five capture patterns over a fragile speech layer

Every product in this category picks a capture pattern, and each one trades consent, reliability and cost differently. A **bought bot API** costs around **$0.50 per recording hour** at Recall.ai (down from $0.70 in early 2026; its calendar API is free) and ships in hours ([Recall.ai](https://recall.ai/pricing)). Competing vendors range from $0.35 to $0.70/hr, and Vexa is open source ([Nylas](https://www.nylas.com/blog/best-meeting-bot-apis/)). A **self-hosted headless-Chrome bot** is what Charcha and, functionally, Claude run. It costs only VM capacity, but it breaks on Meet DOM changes, Google sign-out and hosts who refuse to admit it. Google Meet offers no native media API for bots, and Teams bots need Microsoft's Real-time Media Platform ([Nylas](https://www.nylas.com/blog/best-meeting-bot-apis/)). **Desktop capture** in the Granola style records mic plus system audio with no bot in the call, which leaves consent to the user and suffers audio-routing problems ([Granola docs](https://docs.granola.ai/help-center/taking-notes/transcription)). **Extensions** read captions or tab audio. **Platform transcript import** through the Meet REST API v2 arrives only after the meeting and only on some Workspace plans ([Meet API](https://developers.google.com/workspace/meet/api/reference/rest/v2/conferenceRecords.transcripts.entries/list)). Charcha already covers the bot (Meet and Teams), calendar-triggered joins, an in-person recorder and uploads, so its remaining work is the intelligence and the voice, not capture.

On the LLM side, summaries and action items no longer set a product apart. The 2026 differentiators are **live, permissioned action** (Claude Meetings) and **meeting memory exposed to general assistants through MCP**. Granola (Feb 2026), Read AI (May 2026), Fathom, Fireflies and Otter all ship remote MCP servers, mostly read-only ([Granola](https://www.granola.ai/blog/granola-mcp-claude-chatgpt-cursor); [Read AI](https://read.ai/post/read-ai-mcp-adoption-surges-in-launch-phase); [Fathom](https://developers.fathom.ai/mcp-docs)). Pricing for global notetakers clusters around **$8–19 per user per month** on entry paid tiers. Bundled assistants such as M365 Copilot run $21–30, about ₹2,500 plus GST in India ([Granola comparison, vendor-authored](https://www.granola.ai/blog/meeting-note-tool-pricing-granola-vs-fireflies-fathom-otter); [Cloudfy](https://cloudfysystems.com/blog/microsoft-365-copilot-india)). Language is where they fall short for India. Gemini's "Take notes for me" lists eight languages and **no Hindi** ([The Tech Outlook](https://www.thetechoutlook.com/news/apps/google-rolls-out-take-notes-for-me-feature-in-google-meet-available-for-google-ai-pro-and-ultra-subscribers-in-select-languages/)), and TechRepublic warns teams who switch languages not to trust Gemini's notes ([TechRepublic](https://www.techrepublic.com/article/news-google-meet-in-person-meeting-notes/)). Fireflies claims 14+ Indian languages ([Inc42](https://inc42.com/?p=524104)). The India-native field is thin and early: Acta.ai, Minom, NimitAI, MeetMinutes and JotMe ([Indian Startup News](https://indianstartupnews.com/stories/how-an-india-born-ai-startup-is-turning-messy-meetings-into-measurable-outcomes-for-teams-big-and-small-10646886); [Product Hunt](https://www.producthunt.com/@nimitai)).

### Indian STT: pick a vendor, then distrust every leaderboard

Charcha's choice of **Gnani Prisma v3 in `codemix` / `indic-auto` mode** is defensible, and for this contest it is mandatory. Gnani's Vachana family launched in Dec 2025 under the IndiaAI Mission, trained on more than 1M hours across 10 Indian languages plus Hinglish code-switching ([Gnani blog](https://gnani.ai/resources/blogs/gnani-ai-launches-vachana-stt-a-foundational-indic-speech-to-text-model-trained-on-one-million-hours-under-the-indiaai-mission)). Prisma v3.0 targets telephony-grade audio ([LetsDataScience](https://letsdatascience.com/news/gnani-ai-launches-prisma-v30-speech-to-text-model-for-indian-7163adda)). The alternatives are Sarvam saaras v3/v4 at **₹0.49/min pay-as-you-go** with ₹100 of free credits ([Sarvam pricing](https://docs.sarvam.ai/api-reference-docs/pricing.md)), AI4Bharat IndicConformer (MIT-licensed, self-hosted), and Bhashini, whose API terms allow proof-of-concept use only ([ecorpit](https://ecorpit.com/voicera-bhashini-multilingual-voice-agent-build-india-2026/)).

Benchmarks need care. The one independent 2026 Indian-language benchmark, Humyn Labs' BRIDGE, ranks ElevenLabs Scribe v2 first on WER (8.5%), Deepgram Nova-3 first on code-switch F1 (0.906), and Sarvam saaras v3 at 18.9%. It puts **Gnani Vachana v3 at 35.6% WER, but on only 4 samples** ([BRIDGE](https://humynlabs-bridge-report.pages.dev/)), which is too few to judge it. Gnani's own "#1 in 9 languages" claim is vendor-reported ([Gnani benchmarks](https://asr-benchmarks-research.netlify.app/)). Deepgram's own Hinglish test showed WER from 27% to 70% across models on the same audio ([Deepgram](https://deepgram.com/blog/hinglish-voice-ai-speech-recognition)), which shows how much results depend on the test set. In short, no public benchmark compares Gnani, Sarvam, Deepgram and ElevenLabs on the same Hinglish meeting audio. Charcha's real Hinglish voice memo test is better evidence for the pitch than any leaderboard. One more caveat is Whisper: on code-switched audio it tends to **translate into English rather than transcribe** ([ServiceNow/HF](https://huggingface.co/blog/ServiceNow-AI/code-switching)). The original CLAUDE.md advice to force `language: "en"` on Groq Whisper is therefore stale, and the Gnani migration fixed it.

## Charcha already beats Claude after the call but stays silent during it

Compared feature by feature against the Claude Meetings documentation, Charcha's gaps all sit in the live, in-call layer and in voice output. The repo evidence comes from the team's research notes and was spot-checked for this report: the backend config holds the Gnani `prisma-v3.0` and `codemix` settings, `gemini_api_key` is empty by default, and a search for "tts", "timbre" and "speechSynthesis" across `backend/app` and `frontend/src` found nothing.

| Claude Meetings capability | Charcha | Note |
|---|---|---|
| Bot joins Meet from calendar, auto-join | **Has** | Push-synced calendars, `all/organized/manual` rules, bot invites, single capture queue |
| Platforms beyond Meet | **Exceeds** | Teams by link, in-person `/record` (durable 5-minute segments, consent checkbox), file upload |
| Notes, action items, transcript page | **Exceeds, once Gemini is keyed** | Evidence-quoted tasks/decisions/risks, stand-up digest, contradiction check. **Placeholders today without a Gemini key** |
| Ask about past meetings | **Has** | `/api/chat` over Pinecone multilingual-e5, scoped to readable meetings |
| Pre-meeting brief, Jira two-way sync, follow-up draft | **Has; Claude doesn't document these** | `prep_service`, `jira_service`, follow-up draft opened in Gmail |
| Privacy and consent | **Different, finer-grained** | Invite-based visibility, held tasks, confidential meetings. External attendees get no access, but they *are* recorded; Claude instead leaves when an outsider joins |
| Join notice posted in Meet chat | **Lacks** | No bot chat-posting code found |
| Live Q&A in the call chat, mid-call tool use, live artifacts, in-call recap | **Lacks** | All AI runs after ingest |
| Spoken output | **Lacks (Claude also answers in writing)** | No TTS in the repo, so this is open ground for both products |
| Audio retention | **Opposite** | Charcha keeps audio for playback; Claude stores none. Be ready to defend this in interviews |
| Indic / code-mixed speech | **Differentiator** | Gnani codemix plus learned name corrections; Claude's language support is undocumented |
| Organisations Claude excludes (ZDR, HIPAA-ready, individuals, SMBs) | **Opportunity** | Self-hostable on one VM, rupee-priced economics |

The strategic reading is that **Claude Meetings is a live co-worker with thin memory, and Charcha is deep memory with no live presence**. Copying Claude's headline feature, an in-call chat participant, is the riskiest build and the least relevant to Gnani's judges. Giving Charcha a voice is both Gnani-native and something Claude Meetings doesn't do: it answers in writing by default.

## Today: switch the notes on, give Charcha a Gnani voice, post by 13:00

The ranking below follows one rule: **demoable and postable before 18:00 beats impressive and half-done.** The contest needs a working app using at least one Gnani model. Prisma STT already meets that, so every addition is upside, not a requirement ([Gnani](https://www.gnani.ai/internship)). Evon v3.3 ships as open weights only, with no API, so it is out of scope for today.

**Priority 1, non-negotiable (about 45 minutes): add a Gemini key and regenerate the demo meetings.** Without it, the kirana pilot, ASHA intake and product-sync seeds show placeholder notes, and the video has no payoff. Set `GEMINI_API_KEY` in the production environment and redeploy the backend. Pushing to `main` runs the CI test gate and then deploys; by hand, use `SKIP_PULL=1 tools/deploy.sh`. Then re-run note generation on each seeded meeting through the stage retry or `insight_service.regenerate`. Check that the Hinglish meetings show owners, deadlines and evidence quotes, and that the memory chat answers the exact questions you plan to ask on camera.

**Priority 2, the single Gnani addition (about 4 hours, hard go/no-go at 08:30): "Suno", meaning spoken answers and read-back through Timbre v2.5.** Gnani's docs list `timbre-v2.5` streaming over WebSocket at `wss://api.vachana.ai/api/v1/tts`, with SSE and inference variants ([Gnani TTS docs](https://docs.gnani.ai/api/TTS/tts-websocket.md)). The build is small and stays on the server. Add a backend `POST /api/tts` that takes `{text, language}` and calls Timbre with the Gnani key Charcha already holds. It should collect the audio, cache it by a hash of text and voice (the "nearly free" rule), log a `usage_ledger` row, and return the audio. On the frontend, add a speaker button on memory-chat answers and on the meeting summary, plus a mic button on `/memory` that feeds the existing `/api/transcribe` (Prisma) into `answer_query` and then into TTS. The result is a closed loop, **Prisma hears, Gemini thinks, Timbre speaks**. That loop is the Jugaad Genius story. Spend the first 30 minutes on a raw smoke test against the docs, because the message format, voice names and language list are not yet verified (sources cite 10, 12 or 22 languages). If Timbre isn't speaking Hinglish cleanly by the go/no-go, cut it and ship the STT and notes story. Don't swap in browser `speechSynthesis` and call it Gnani.

**Priority 3, polish over features.** Make the "Powered by Gnani Prisma" provenance visible on the meeting page, for example a small badge next to the transcript. Fix any visual roughness on the three screens that appear in the video. Rehearse the vocabulary fix for a name the STT misspells, because it is a 3-second "it learns Indian names" moment. Build nothing else today: no WhatsApp, no MCP, no in-call bot.

### The 60-second video

Platform autoplay is often muted, so burn in captions throughout, keep the Hinglish natural, and show the brand only in the last 5 seconds.

| Time | Shot | Line (spoken or caption) |
|---|---|---|
| 0–6 s | Phone on a kirana counter, `/record` running | "Claude ab Google Meet join karta hai. Par India ki asli baatein counter pe hoti hain, Hinglish mein." |
| 6–20 s | Team role-play: shopkeeper and supplier, scripted and synthetic | "Sharma ji ko do kilo atta udhaar, 120 rupaye… Friday tak supplier ko call karna hai." Caption: *Gnani Prisma, codemix* |
| 20–34 s | Notes page fills in: tasks with owners and dates, an evidence quote highlighted in the code-mixed transcript | "Kaun, kya, kab tak, aur kis line pe bola gaya." |
| 34–50 s | Tap the mic: "Sharma ji ka kitna baaki hai?" The answer appears with a citation, then **Timbre speaks it** in Hindi | Caption: *Prisma STT → Gemini → Timbre TTS* |
| 50–56 s | Quick cut: ASHA home-visit intake turns into a referral task, then "Suno" plays the summary | "Wahi Charcha, ASHA didi ke liye bhi." |
| 56–60 s | `BrandMark`, wordmark, tags | "Charcha. Bolo, suno, yaad rakho." #GreatIndianAIInternshipChallenge #GnaniAI |

Before recording, check that the kirana seed actually contains the fact behind the "kitna baaki" question, and reword the question if it doesn't. Record the counter scene as a fresh, scripted role-play. **The contest says synthetic data only**, so don't put the earlier real voice memo in the video.

### Award categories to target

The award categories come from the official page ([Gnani](https://www.gnani.ai/internship)), and the copy and caption should hit them explicitly. **Mixed Vibes** fits because code-mixed Hinglish is the whole premise: say "codemix" on screen. **Real Deal** fits the kirana and ASHA scenarios, which map directly to its kirana and rural-health-worker examples. **Demo Day Drop** rewards the best 60-second video. **Jugaad Genius** rewards creative use of Gnani models, and the Prisma-to-Timbre loop is that story, so it only applies if Priority 2 ships. **Two-Person Army** applies if the entry is filed as a two-person team. The contest allows one entry per team, so agree the roster before submitting.

### Checklist with time-boxes (IST, 15 Nov)

| Window | Person A | Person B | Exit criterion |
|---|---|---|---|
| 01:00–01:45 | Get a Gemini key, set it in prod, redeploy | Read the Timbre docs, write a smoke-test script | Backend healthy with the key |
| 01:45–02:15 | Regenerate notes on every demo seed, verify them | Timbre smoke test: Hindi and Hinglish sentence to audio file | **Go/no-go 1**: Timbre returns audio |
| 02:15–04:00 | Write the video script, draft post copy for LinkedIn and X, pick the demo questions and test them in memory chat | `POST /api/tts` with cache and ledger row; speaker button on chat answers | Answer audio plays locally |
| 04:00–08:00 | **Sleep** | **Sleep** | — |
| 08:00–10:30 | Polish the three demo screens, add the Gnani badge, rehearse the name correction | Mic button on `/memory`, summary read-back, deploy | **Go/no-go 2 (08:30)**: keep or cut TTS |
| 10:30–11:00 | Full dry run on the deployed app from a phone | Fix only blockers | **Code freeze 11:00** |
| 11:00–13:00 | Record scenes, voice the narration | Edit to exactly 60 s, burn in captions, export vertical and landscape | Final MP4 |
| 13:00–13:30 | Post on LinkedIn and X, tag Gnani AI, add both hashtags, pin a comment with the app link | Share with your network and ask for genuine comments | Both post URLs live |
| 13:30–16:00 | Fill the form: explanation, models (Prisma v3 codemix, Timbre v2.5 if shipped, Gemini), both post links | Reply to every comment; prepare interview talking points (audio retention, privacy layer, benchmark honesty) | Draft form complete |
| 16:00–16:30 | **Submit the form** | Screenshot the confirmation | Submitted with a 90-minute buffer |

The contest page doesn't say whether engagement after 18:00 counts, so posting by 13:00 buys five hours of measurable engagement either way. Don't deploy after the freeze. A backend restart during a demo recording costs more than any late fix is worth.

## After 18:00: one voice layer, four directions

Everything below reuses today's TTS endpoint, and none of it should be started before the form is submitted.

**WhatsApp voice follow-ups (about 2 days) are the highest-impact next build.** After notes are ready, each task owner gets a voice note plus text in their language. A reply such as "pehla wala ho gaya" goes through Prisma, then intent detection, then a task status change, and a voice question sent to the number goes into memory Q&A. Meta's Cloud API sends voice notes as `type: audio` with `voice: true`, which must be **OGG/Opus mono**. Charcha's ffmpeg pipeline already produces Ogg for Gnani. Files up to 16 MB are allowed, and a "played" webhook has existed since Mar 2026 ([Meta audio](https://developers.facebook.com/docs/whatsapp/cloud-api/messages/audio-messages)). Pricing is per message. Free-form replies are allowed inside the 24-hour window, and each number gets 1,000 free service messages a month, with charges beyond that from 1 Oct 2026 ([Meta pricing](https://developers.facebook.com/docs/whatsapp/pricing)). Build it on the Meta test number and the existing `email_outbox` pattern.

**An MCP connector (about 1 day with bearer auth, plus 1–2 days for claude.ai OAuth)** makes Charcha the memory behind Claude Meetings rather than a rival. The pitch: "Claude sits in the call, and Charcha remembers in Hindi." Mount FastMCP inside the FastAPI app with `app.mount("/mcp", mcp.http_app(path="/"))` and combine the lifespans, or the session manager won't start ([FastMCP](https://gofastmcp.com/integrations/fastapi)). Hand-write five read tools, `search_meetings`, `get_meeting`, `get_tasks`, `get_decisions` and `ask_memory`, plus `create_task` annotated as a write. Every tool must route through `user_can_read_meeting` and `privacy_service`. For claude.ai, the spec requires RFC 9728 protected-resource metadata, PKCE S256, an audience-bound `resource` parameter, and no token pass-through ([MCP spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)). Claude's client needs a 401 with `WWW-Authenticate: Bearer resource_metadata=…`, the callback `https://claude.ai/api/mcp/auth_callback`, and tools annotated with `readOnlyHint` or `destructiveHint` for directory listing ([Claude auth](https://www.claude.com/docs/connectors/building/authentication); [submission](https://claude.com/docs/connectors/building/submission)). Charcha's 30-day HS256 JWTs aren't audience-bound, so mint separate MCP tokens. nginx must proxy `/mcp` without buffering. It is worth building for parity, but it won't differentiate Charcha: every notetaker already ships one.

**A live in-call co-pilot (3+ days, high risk)** is the only way to match Claude's headline feature. The bot would post a join notice, which also closes a consent gap, watch Meet chat for "Charcha, …", answer in chat or in Timbre's voice, and post a recap before the call ends. It depends on Meet DOM automation and streaming STT, and the notes didn't verify that the current Playwright bot can post to chat. Build the join notice first, because it is cheap and is a privacy win in its own right.

**The Scaler × Wispr hackathon is optional.** Registration closes 27 Nov, the shared problem statement comes out the same day, and the build is due 29 Nov ([Scaler](https://hackos.scaler.com/wispr/)). If the team enters, the voice-out layer and WhatsApp loop are track-agnostic: kirana fits small business, ASHA fits healthcare, and gram sabha minutes fit civic. Judging criteria and any Wispr Flow requirement are unpublished until each round goes live.

## Source conflicts and unverified claims

| Topic | Conflict or uncertainty | How to treat it |
|---|---|---|
| Claude's external-guest default | The article says Claude stays out of calls with outsiders by default; the Help Center says Team plans *allow* guests by default ([article](https://claude.com/resources/articles/claude-meetings) vs [Help Center](https://support.claude.com/en/articles/18325154)) | Help Center is more specific; the article likely describes Enterprise |
| Gnani naming and benchmarks | Hugging Face mixes "Vachana" and "Prisma v2.5"; BRIDGE scores Vachana v3 on 4 samples; Gnani's own leaderboard is vendor-run | Don't quote any WER figure in the pitch; show the live demo instead |
| Timbre TTS | 10 / 12 / 22 languages depending on source; the WebSocket message format is unverified; the contest labels it beta | Smoke-test it before building; go/no-go gates |
| Sarvam STT price | ₹0.49/min (docs) vs ₹1.5/min (marketing page) ([docs](https://docs.sarvam.ai/api-reference-docs/pricing.md); [page](https://www.sarvam.ai/speech-to-text)) | Docs are authoritative |
| Otter MCP | One source lists an official endpoint; an older one says there is none | Unresolved; irrelevant today |
| Fathom acquisition | A Sep 2026 Superhuman acquisition is reported by one secondary source only | Unverified |
| Competitor pricing | Mostly vendor-authored (Granola) or aggregators | Indicative only |
| CLAUDE.md internals | It still describes Claude Haiku extraction and Deepgram keyterms, while the live stack uses Gemini and Gnani; it is unverified whether the keyterm list reaches Gnani | Check the vocabulary hint path before claiming "learns names" on camera |
| "Synthetic data only" | The earlier real Hinglish voice memo may not qualify | Use scripted team role-play in the video |
| Engagement window | The contest page doesn't say whether engagement after the deadline counts | Post early regardless |

Also unverified: WhatsApp test-number recipient limits, Meet chat automation from the bot, and whether FastMCP's `JWTVerifier` accepts HS256 keys.

## Conclusion

Claude Meetings redefines the meeting assistant as something present in the call rather than something that produces notes afterwards. Its own constraints (Meet only, written answers, Team and Enterprise plans, no stated Indic support) show where the market isn't served yet: conversations that happen off the video call, in mixed languages, among people who would rather listen than read. Charcha's advantage is not that it records more meetings than Claude. It hears Hinglish and, once Timbre is wired in, it can answer out loud. That turns a feature gap into a positioning statement, and the post-deadline builds (WhatsApp voice, the MCP connector, an in-call voice) all extend it.

For today, the binding constraint is attention, not engineering. Missing the Gemini key would sink a strong demo, a TTS feature still unfinished at 11:00 would cost the posting window, and a post at 17:30 would forfeit most of the engagement that shortlisting depends on. Spend the 17 hours so that switching on the notes, adding one voice and publishing early all happen in that order.

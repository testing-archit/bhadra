# Charcha testing guide

Live app: https://34-58-54-115.sslip.io. Plain-HTTP requests to the server's IP redirect here. HTTPS is required for the microphone.

- **Logins:** the two admin accounts are pinewoodarchit@gmail.com and vedantmoghe16@gmail.com. Passwords are shared privately, never in git. Change them in Settings.
- **Demo data:** all synthetic. It's 10 Hinglish meetings, created by `backend/scripts/seed_demo.py`. Re-running the script adds anything missing and leaves your edits alone; `--reset` rebuilds everything.

## 1. Home, ask by voice and read aloud (Gnani Prisma + Timbre)

| Try | Expect |
|---|---|
| Click the chip "Sharma ji ka kitna udhaar baaki hai?" | Memory answers with amounts: Rs 6,750 owed by 14 customers, Gupta ji Rs 1,100 the largest; Sharma ji owes Ramesh Rs 1,240 |
| Tap the marigold mic and say "Is hafte kya decide hua?" | Gnani transcribes it, the answer lists decisions by meeting with citations, and **it's read aloud automatically** |
| Under any answer, press **Listen** | Timbre reads it in Hinglish; the button switches to Stop |
| Meeting page → Detailed summary → **Listen** | The summary is read aloud |

More questions with known answers in the demo data:

- "Vedant ke paas kaunse tasks pending hain?" → vocabulary names, the month-end WhatsApp statement, the retention chart, mapping the intake form fields, the slower speech option, the sugar and oil order.
- "Statements WhatsApp pe kyun bhejenge, SMS pe kyun nahi?" → Every shopkeeper and most customers use WhatsApp daily; SMS and printed slips were rejected.
- "Ward 7 mein paani kab se nahi aaya aur kab tak theek hoga?" → Three days without water; the pipeline is fixed by Friday; the tanker comes at 7 am until then.
- "PTM mein parents ne kya maanga?" → A Tamil option, a weekly WhatsApp report, and no quizzes after 9 pm.
- "Older users ko kya problem thi?" → Small buttons; speech too fast; they want bigger text and Marathi.
- "Kaunse decisions pehle wale decisions ko palat diye?" → The 2-minute demo video, and Baloo 2 + Mukta fonts (the two reversals).
- "Sabse bade risks kya hain?" → Shop noise, health-data consent, pipeline delay, the 2-day build window, untested Tamil with children, and more.

## 2. Charcha Live (sidebar → Ask → Charcha Live)

1. Tap **Start talking** and allow the microphone.
2. Just talk, with no button to hold. Try these:
   - "Sharma ji ka kitna udhaar baaki hai?" → it answers in Hinglish with the exact amounts.
   - Then follow up with "Aur Gupta ji ka?" → it keeps the conversation's context.
   - In Tamil, "சர்மா ஜிக்கு எவ்வளவு பணம் பாக்கி உள்ளது?" → it replies in Tamil and speaks Tamil.
   - "Is hafte kya decide hua?", "Ward 7 ka paani kab aayega?", "PTM mein parents ne kya bola?"
3. **Interrupt** while it's speaking: start talking and it should stop and listen.
4. Below the orb, a chip shows the language it heard.

## 3. Notetaker in a Google Meet (Stages 3–5)

1. Start a Meet, then Home → **Capture a meeting** → paste the link.
2. Admit **Charcha Notetaker**. It's the gnanihackathon@gmail.com Google account, signed in through `auth.json` on the server.
3. **Join notice:** a chat message says who invited it, that it's recording, how to stop it, and where the notes will appear.
4. Turn on captions (CC) and talk for about 30 seconds in Hinglish.
5. In chat, type:
   - `Charcha recap` → key points, decisions and action items so far.
   - `Charcha, kya decide hua?` → an answer from this call only.
   - `Charcha, add task: Vedant to send the invoice by Friday` → "Added for Vedant: Send the invoice (by Friday)…"
   - Or **say it aloud**: "Charcha, kya decide hua?" (captions on). It answers in chat **and speaks** the answer in the call.
6. Say "**charcha please leave**", or end the call. A few minutes later the meeting appears with notes, and the added task is on it.

Watch it live on the server:

```bash
docker compose -f docker-compose.prod.yml logs -f notetaker
```

Each session saves screenshots in `/data/sessions/<id>/`.

## 4. Claude connector (MCP)

1. Settings → **Connect Claude** → Create connector token.
2. Paste the `claude mcp add ...` command it shows into a terminal with Claude Code.
3. Ask Claude: "Search my Charcha meetings for the kirana pilot", "What are my open tasks in Charcha?", "Add a Charcha task: call Sharma ji tomorrow".

## 5. Every page should load

Pages to open: Home, Meetings, a meeting, Tasks (board and list), Decisions, Projects, a project, Company memory, Policies, Vocabulary, Admin, Settings, Record, New meeting (upload and paste), Prepare for a meeting, Chrome extension.

- **Earlier crash, now fixed:** the demo seed once wrote `null` lists, which made pages show "This page couldn't load". That's fixed in the API, the pages and the seed.
- **If a page crashes again:** open the browser console, and report the error together with the page URL.

## 6. Known gaps

- Live docs and whiteboards during a call aren't built.
- The notetaker doesn't speak in the call.
- Memory search uses the "recent meetings" fallback because no Pinecone key is set. Add `PINECONE_API_KEY` for full vector search.
- The Chrome extension's Google sign-in uses an old OAuth client ID in `manifest.json`. Replace it with your own before publishing.

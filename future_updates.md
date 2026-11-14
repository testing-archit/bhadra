Based on the current extension, here are the most valuable things you could add:

## High Impact Features

**1. Real-time Live Transcript Widget**
Show a scrolling transcript in the overlay widget during the meeting — people love seeing it work in real-time instead of waiting until after.

**2. Google Calendar Integration**
Pull the meeting title, attendees, and agenda from the Calendar API automatically — better context = better task extraction, and you stop relying on the page title.

**3. Email Summary (Gmail API)**
After the meeting, auto-draft or auto-send a summary email to attendees with tasks and who owns them.

**4. Pause / Resume Recording**
Add a pause button to the in-meeting widget — users don't want to record confidential parts.

## Integrations

**5. Slack** — Post summary + tasks to a channel after the meeting ends
**6. Notion / Jira** — Push tasks directly instead of only Google Sheets
**7. Google Docs** — Write the full transcript + summary to a Doc (not just Sheets)

## Smarter Extraction

**8. Meeting type templates** — Different prompts for standup, sales call, design review, 1:1 — each extracts different things (blockers vs. deal status vs. decisions)

**9. Key decisions extraction** — Separate from tasks, track what was *decided* not just what needs to be done

**10. Attendee detection** — Scrape participant names from the Meet UI and assign tasks to real names instead of "You" / "Others"

## Quality of Life

**11. Multi-language support** — Currently hardcoded to English in the Whisper call (`language: "en"`) — easy to expose as a dropdown

**12. Keyword alerts** — Flag when specific words (budget, deadline, competitor names) appear in the transcript

**13. Action item completion tracking** — Let users mark tasks done from the popup, sync back to Sheets

---

The highest ROI additions are probably **live transcript**, **pause/resume**, and **Slack integration** — those are the ones users ask for most in tools like this.     
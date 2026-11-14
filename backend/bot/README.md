# Bhadra Notetaker bot

Works like Fireflies' `fred@fireflies.ai`: **add `notetaker@example.com` as a guest
on any Google Calendar event with a Meet link**, and the notetaker joins the call a minute
before it starts. It records the call and sends it to Charcha, which files the meeting under
the event organizer (or the first invitee with a Charcha account). Every invitee with a
Charcha account can then read it.

Nobody has to install the extension or connect their own calendar.

## How it works

```
invite notetaker@example.com ──► event lands on the notetaker's own Google Calendar
                                               │
scheduler.py (polls every 30s via Calendar API)┘── RSVPs "yes", then 60s before start:
   └─► meeting_session.py (one process per meeting)
         • Chromium on Xvfb, signed in as the notetaker (data/auth.json)
         • joins the Meet, mic muted (and its "mic" is a silent sink anyway)
         • ffmpeg records the meeting's audio from a private PulseAudio sink
         • scrapes Meet's live captions for speaker names + timings
         • leaves 30 s after everyone else has left (ALONE_TIMEOUT_SECONDS), when the
           host removes it, someone says "notetaker please leave", Stop is pressed in
           Charcha, or the event runs 60 min over
         • "Send notetaker" requests are picked up within ~3 s (CAPTURE_POLL_SECONDS)
   └─► POST /api/bot/ingest (audio + captions + calendar invitees)
         • Deepgram diarizes the audio; caption timings put real names on the speakers
         • normal Charcha pipeline: summary, tasks, decisions, attendee access, playback
```

If an upload fails it stays in `data/pending_uploads/` and is retried every 10 minutes.

## Microsoft Teams

Paste a Teams link into **Send notetaker** (web app or extension) and the same notetaker joins it.
Accepted: `teams.microsoft.com/meet/<id>?p=<passcode>`, `teams.live.com/meet/<id>`,
`teams.microsoft.com/l/meetup-join/...`, and any of those wrapped by Outlook Safe Links.

- It joins as an **anonymous guest** named `BOT_DISPLAY_NAME`, with no Microsoft account, so
  usually someone has to admit it from the lobby. A meeting or tenant that turns off anonymous
  join refuses it, and Charcha says so (`Blocked by Google Meet or Teams` in Admin → Notetaker).
- Calendar invites and linked calendars still only auto-join Google Meet.
- Speaker names come from Teams' live captions. A tenant can turn those off; the transcript then
  keeps `Speaker 1/2/…`, as with Meet.
- Guests can't have a profile picture, so Teams shows its own icon. `TEAMS_LOGO_CAMERA=1` (off by
  default) shows the Bhadra logo (`assets/logo_card.png`) as the notetaker's camera instead. It
  costs CPU, so check the recording for gaps on the real server before leaving it on.
- Everything Microsoft-specific is in `teams_dom.py`. Teams links carry a passcode, so log them
  through `loggable_url`.

## One-time setup

### 1. The Google account (`notetaker@example.com`)
- Set its profile name to **Bhadra Notetaker**. That is the name people see in Meet.
- Google Calendar → Settings → *Event settings* → **Add invitations to my calendar** →
  set it to **From everyone**. Otherwise invites from people the account has never emailed
  never reach the calendar, and the bot never sees them.

### 2. Calendar access (refresh token)
You need a Google Cloud OAuth client of type **Desktop app**. The `client_secret_…json` in
the repo root is **not** one — it is the Chrome extension's client, which has no secret and
cannot redirect to a local port (Google answers "Error 400: invalid_request"). Create a
Desktop client (Google Auth Platform → Clients → Create client → Desktop app), download its
JSON, and use that file below. In that Cloud project:
- Enable the **Google Calendar API**.
- OAuth consent screen: set the publishing status to **In production**. While it is in
  *Testing*, Google expires refresh tokens after 7 days and the bot stops seeing invites.
  You will see an "unverified app" warning when you sign in; click through it. That is fine
  for an internal account.

Then, on your laptop:
```bash
cd backend/bot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python authorize_calendar.py /path/to/desktop-client.json
```
Sign in as **notetaker@example.com**. It prints three `GOOGLE_…` lines.

### 3. Meet login (`auth.json`)
```bash
.venv/bin/playwright install chromium
.venv/bin/python generate_auth.py      # sign in as notetaker@example.com
```
This writes `auth.json`, which is a live login. Never commit it. If the session ever
expires, the bot keeps working as a guest that the host has to admit, and the logs say so.
To fix it, run this step again.

### 4. Secrets
```bash
openssl rand -hex 32                   # the shared bot secret
```
- `backend/.env`: add `BOT_API_SECRET=<that value>`
- `backend/bot/.env`: copy `.env.example`, then fill in `BOT_API_SECRET` (same value) and the three `GOOGLE_…` lines

### 5. Deploy (on the server)
```bash
docker compose -f docker-compose.prod.yml up -d --build backend notetaker
docker compose -f docker-compose.prod.yml cp backend/bot/auth.json notetaker:/data/auth.json
docker compose -f docker-compose.prod.yml logs -f notetaker
```

## Testing it
- **Calendar flow:** make an event 3 minutes from now with a Meet link, add
  `notetaker@example.com`, and watch the logs. You should see it accept the invite,
  then `Joining …`, then `Admitted`.
- **Ad hoc, no calendar:**
  `docker compose -f docker-compose.prod.yml exec notetaker ./entrypoint.sh --url https://meet.google.com/xxx-yyyy-zzz --organizer you@example.com`
- Each session saves screenshots to `/data/sessions/<id>/` (`01_loaded`, `02_prejoin`,
  `03_admitted`, `99_error`, …). Check these first when a join fails.

- **Teams, ad hoc:** `... exec notetaker ./entrypoint.sh --url "https://teams.microsoft.com/meet/<id>?p=<passcode>" --organizer you@example.com`
  (the quotes matter, because of the `?`).

## Things to know
- **Admission:** a calendar invitee usually skips the lobby. If the host's Workspace blocks
  outside accounts, someone has to click *Admit*. The bot waits 10 minutes
  (`LOBBY_TIMEOUT_SECONDS`).
- **Capacity:** each concurrent meeting is a full Chromium, about 700 MB RAM.
  `MAX_CONCURRENT_MEETINGS` defaults to 2. Raise it only if the VM has the memory.
- **Audio quality depends on spare CPU.** There is no GPU, so any video Chromium draws is
  CPU work, and a starved Chromium drops audio. The bot hides all video in Meet (it only needs
  audio and captions) and plays into PulseAudio with 300 ms buffers (`PULSE_LATENCY_MS`).
  The sign of a starved bot is regular bursts of exact silence (tens of ms, several per second)
  in the recording. If that still happens, the VM is out of CPU: lower `MAX_CONCURRENT_MEETINGS`
  or move the notetaker off the API VM.
- **Adding capacity:** run another notetaker container anywhere that can reach the backend —
  a second VM, a spot instance — with the same `BOT_API_SECRET`, `BACKEND_URL` and `auth.json`.
  Requests are claimed with `SELECT … FOR UPDATE SKIP LOCKED`, so containers never take the same
  meeting. Set `NOTETAKER_INSTANCE_NAME` to tell them apart; Admin → Notetaker shows each one's
  size, load and last check-in. Keeping notetakers off the API VM also keeps Chromium's memory
  away from the backend.
- **Meetings with no Charcha user on the invite** are dropped, because there is nobody to file
  them under.
- **Speaker names** come from Meet's caption DOM, whose class names Google changes now and
  then. When they break, transcripts still come through with `Speaker 1/2/…`, and people
  can rename speakers in the meeting page.
- Recording people needs their consent. Tell attendees the notetaker is recording.

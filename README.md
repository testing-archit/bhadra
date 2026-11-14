# Charcha

Charcha captures Google Meet conversations and turns them into a searchable company memory. The project includes a Chrome extension for meeting capture, a FastAPI service for transcription and extraction, and a Next.js workspace for meetings, tasks, decisions, projects, digests, policy search, and usage analytics.

## What is included

- Automatic Google Meet detection, caption capture, and audio fallback
- Real pause, resume, and skip controls for sensitive or irrelevant discussion
- Offline IndexedDB queue with automatic retry
- Deepgram Nova-3 transcription with Hindi, English, and Hinglish support
- AI extraction of summaries, tasks, decisions, risks, owners, deadlines, and projects
- Attendee-scoped meeting access (only the people in a meeting can read it) and admin analytics
- Searchable meeting memory with cited answers and related meetings
- Contradiction detection across past decisions
- Weekly digest and decision-churn simulator
- Google Sheets export from the extension
- Manual transcript or recording upload from the web app
- One-click physical and online meeting recording with pause/resume, audio-level feedback, bookmarks, and consent capture
- Five-minute durable recording segments stored in IndexedDB before upload, designed for 3-4 hour sessions and network recovery
- Full authenticated audio playback/download after processing
- Gemini-generated summaries, topics, highlights, open questions, next steps, tasks, decisions, risks, and speaker participation
- Global meeting library with many-to-many project assignment: one project can contain many meetings and one meeting can span several projects
- Markdown export for processed meetings
- Separate policy assistant with conversation history and citations

## Architecture

| Area | Location | Stack |
| --- | --- | --- |
| Chrome extension | `src/`, `manifest.json` | Manifest V3, Vite |
| Web workspace | `frontend/` | Next.js 16, React 19, TypeScript, Tailwind CSS |
| API | `backend/` | FastAPI, SQLAlchemy async, PostgreSQL |
| Semantic memory | `backend/app/services/qdrant_service.py` | Qdrant, FastEmbed |
| AI processing | `backend/app/services/` | Deepgram, Gemini |

Meetings are recorded by the notetaker bot (`backend/bot/`), which joins a Google Meet when invited from a calendar event, from the web app, or from the Chrome extension. The extension itself never captures audio: it sends and stops the notetaker, shows its status inside Meet and on the toolbar badge, notifies when notes are ready, lists your open tasks, answers questions from company memory, and copies finished notes to Google Sheets. The backend persists the extracted record in PostgreSQL and indexes searchable content in Qdrant. The web workspace reads the same API, so extension and web data stay in sync.

## Quick start with Docker

1. Create the backend environment file:

   ```bash
   cp backend/.env.example backend/.env
   ```

2. Add `GEMINI_API_KEY` and `DEEPGRAM_API_KEY`. Google OAuth credentials are optional when using email/password login.

3. Start the application:

   ```bash
   docker compose up --build
   ```

4. Open `http://localhost:3000`. The API health endpoint is `http://localhost:8080/health`.

PostgreSQL is exposed on host port `5433`; Qdrant is exposed on `6333`.

## Local development

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload --port 8080
```

Frontend:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Extension:

```bash
npm install
npm run dev
```

Always load the repository's `dist/` directory as the unpacked extension. `npm run dev` rebuilds that directory in watch mode; reload the extension from `chrome://extensions` after a change. Do not load the repository root: it contains development files that Chrome should never treat as extension assets. For a one-off distributable build, run `npm run build` and load the same `dist/` directory. The shared deployed API origin lives in `src/config.js`; matching origins must also be present in `manifest.json`.

After changing extension code, run the integration checks and rebuild:

```bash
npm test
npm run build
```

Reload the unpacked extension at `chrome://extensions`, then reload any open Meet tab. In a short test call, confirm that the Charcha control appears in the call, **Invite notetaker** brings the bot to the lobby, the toolbar badge changes to `REC` once it is admitted, **Stop notetaker** makes it leave, and a "notes are ready" notification opens the meeting. To review the popup design without installing anything, serve `src/` over HTTP and open `popup.html?preview=1` (or `?preview=login`, `?tab=meet`); it runs on built-in sample data.

Release checklist: bump `version` in `manifest.json` and `package.json`, update `extensionVersion` in `frontend/src/app/extension/page.tsx`, then run `npm run build:production` and zip `dist/` to `frontend/public/downloads/charcha-extension-v<version>.zip`.

Google OAuth requires a Chrome extension OAuth client for `manifest.json` and a web OAuth client in `NEXT_PUBLIC_GOOGLE_CLIENT_ID`. Email/password authentication works without Google OAuth.

## Environment

The complete backend template is in `backend/.env.example`. Important values:

- `DATABASE_URL`: async PostgreSQL connection URL
- `QDRANT_URL`: Qdrant service URL
- `GEMINI_API_KEY`: extraction, memory answers, policy answers, and contradiction checks
- `DEEPGRAM_API_KEY`: audio transcription
- `JWT_SECRET`: application session signing secret; replace the development value in production
- `TEAM_ROSTER`: comma-separated names used as transcription keyterms
- `ADMIN_EMAILS`: comma-separated accounts with organization-wide access
- `ALLOWED_ORIGINS`: comma-separated browser origins allowed by CORS

## Validation

```bash
npm run build
cd frontend && npm run lint && npm run build
cd ../backend && .venv/bin/pytest -q
```

Backend tests require a reachable PostgreSQL database configured through `backend/.env`. External AI and Qdrant calls are mocked in route tests where appropriate.

## Deployment status

Local development runs the web workspace at `http://localhost:3001` and the API at `http://localhost:8080`. The production deployment is temporarily served at `http://34.131.207.226` (reserved static IP); its final hostname will be `https://charcha.example.com` after DNS and TLS are configured. Use `npm run build` for a local extension build and `npm run build:production` for the production Chrome package so login, meeting capture, processing, and deep links use the correct shared Charcha environment.

### Extension releases and automatic updates

The web app exposes `/extension` as the first-install page. Before the Chrome Web Store listing is available it serves the versioned ZIP from `frontend/public/downloads/`; set `CHROME_WEB_STORE_URL` in the VM root `.env` after publication to switch the primary action to the Store listing on the next frontend build.

The checked-in manifest key keeps the extension ID stable as
`cdikchmjlbpieggcpdcpndlohoilelji`. Tag a release such as
`extension-v1.2.0` to build a production Chrome Web Store ZIP in GitHub
Actions. Upload that ZIP to the existing Chrome Web Store item with the same
ID and publish it. Chrome Web Store installs then update automatically when a
higher manifest version is published.

Chrome does not auto-update extensions installed with **Load unpacked**. Each
existing development user must remove the unpacked copy and install the Web
Store version once; subsequent releases update automatically. Do not add a
private signing key to this repository—the public manifest key is sufficient
to preserve the development extension ID.

Never commit `.env`, Google client-secret files, extension private keys, or generated recordings.

## Long meeting storage

The web recorder rotates the microphone into independently playable five-minute WebM segments. Each segment is written to browser IndexedDB before it is uploaded and transcribed, so the page never keeps a multi-hour recording in memory. Interrupted sessions appear under **Recover a session**. On finalization, FFmpeg joins the segments into one stored audio file, Deepgram performs a global word-level diarization pass, and the transcript is processed by Gemini.

Production deployments must persist `RECORDINGS_DIR`. The included Docker Compose configuration mounts the `recordings_data` volume at `/app/recordings`.

If Qdrant is unavailable during ingestion, the meeting still commits and reports semantic indexing as pending. After Qdrant recovers, rebuild one meeting with `python scripts/reindex_meetings.py --meeting-id <uuid>` or omit the ID to rebuild the full meeting index.

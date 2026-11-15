# Develop and deploy Wilco

Commands run from the repository root unless a `cd` is shown. [Back to the product](../README.md).

## Quick start with Docker

1. Create the backend environment file:

   ```bash
   cp backend/.env.example backend/.env
   ```

2. Add `GEMINI_API_KEY` and `GNANI_API_KEY`. Google OAuth credentials are optional when using email/password login.

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
echo "NEXT_PUBLIC_BACKEND_URL=http://localhost:8080" > .env.local
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

Reload the unpacked extension at `chrome://extensions`, then reload any open Meet tab. In a short test call, confirm that the Wilco control appears in the call, **Invite notetaker** brings the bot to the lobby, the toolbar badge changes to `REC` once it is admitted, **Stop notetaker** makes it leave, and a "notes are ready" notification opens the meeting. To review the popup design without installing anything, serve `src/` over HTTP and open `popup.html?preview=1` (or `?preview=login`, `?tab=meet`); it runs on built-in sample data.

Release checklist: bump `version` in `manifest.json` and `package.json`, update `extensionVersion` in `frontend/src/app/extension/page.tsx`, then run `npm run build:production` and zip `dist/` to `frontend/public/downloads/wilco-extension-v<version>.zip`.

Google OAuth requires a Chrome extension OAuth client for `manifest.json` and a web OAuth client in `NEXT_PUBLIC_GOOGLE_CLIENT_ID`. Email/password authentication works without Google OAuth.

## Environment

The complete backend template is in `backend/.env.example`. Important values:

- `DATABASE_URL`: async PostgreSQL connection URL
- `QDRANT_URL`: Qdrant service URL
- `GEMINI_API_KEY`: extraction, memory answers, policy answers, and contradiction checks
- `GNANI_API_KEY`: Gnani Prisma transcription and Timbre speech generation
- `JWT_SECRET`: application session signing secret; replace the development value in production
- `TEAM_ROSTER`: comma-separated names used as transcription keyterms
- `ADMIN_EMAILS`: comma-separated admin accounts; their ordinary workspace lists still follow meeting visibility rules
- `ALLOWED_ORIGINS`: comma-separated browser origins allowed by CORS

## Validation

```bash
npm run build
cd frontend && npm run typecheck && npm run build
cd ../backend && .venv/bin/pytest -q
```

Backend tests require a reachable PostgreSQL database configured through `backend/.env`. External AI and Qdrant calls are mocked in route tests where appropriate.
`npm run lint` is currently blocked by the repository's TypeScript 7 / typescript-eslint compatibility issue.

## Deployment

Every push to `main` runs **Test and deploy** (`.github/workflows/deploy-vm.yml`):
1. **Checks:** it runs only the checks the change needs (backend tests, frontend type check, extension checks).
2. **Build:** it builds only the changed Docker images on GitHub, with a layer cache.
3. **Ship and restart:** it ships those images to the VM over SSH, then restarts each service only when it's idle, so a live meeting is never cut off.

A docs-only push does not deploy application images.

The VM serves HTTPS at the sslip.io name of its IP, with a Let's Encrypt certificate from the bundled certbot. HTTPS is required for the microphone. The server's nginx HTTPS config is `nginx/ssl.conf`, which is local to the server and git-ignored. Copy `nginx/ssl.conf.example` to set it up for a real domain.

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

The web recorder rotates the microphone into independently playable five-minute WebM segments. Each segment is written to browser IndexedDB before it is uploaded and transcribed, so the page never keeps a multi-hour recording in memory. Interrupted sessions appear under **Recover a session**. On finalization, FFmpeg joins the segments into one stored audio file, Gnani Prisma creates the final code-mixed transcript, and Gemini turns it into notes, decisions and tasks.

Production deployments must persist `RECORDINGS_DIR`. The included Docker Compose configuration mounts the `recordings_data` volume at `/app/recordings`.

If Qdrant is unavailable during ingestion, the meeting still commits and reports semantic indexing as pending. After Qdrant recovers, rebuild one meeting with `python scripts/reindex_meetings.py --meeting-id <uuid>` or omit the ID to rebuild the full meeting index.

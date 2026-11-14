# Backend

## Transcription (Deepgram Nova-3)

`app/services/transcriber.py` calls Deepgram's Nova-3 model
(`language=multi`, auto-detects Hindi/English code-switching) instead of
Groq Whisper. On real Hinglish meeting audio it correctly recognized names
and technical terms (GoDaddy, GCP) with zero configuration, where Whisper
needed a prompt-glossary hack and still missed things. Two features Whisper
doesn't have, both wired up:

- **Keyterm prompting** — `TEAM_ROSTER` (backend/.env, comma-separated
  names) is passed as `keyterm` params, a purpose-built and more accurate
  replacement for the old Whisper prompt-glossary trick.
- **Speaker diarization** (`diarize_model=v2`) — word-level speaker labels,
  timestamps, recognition confidence, and speaker confidence are converted
  into turns. Isolated low-confidence label flips are smoothed while real
  multi-word speaker changes are preserved.
- **Global final pass** — chunks are transcribed durably during long meetings,
  then the assembled recording is diarized again as one file. This prevents
  speaker IDs from resetting at every five-minute chunk boundary.
- **Human review** — the meeting page exposes confidence diagnostics,
  timestamped playback, full-audio reanalysis, and editable speaker names.

Set the roster in `backend/.env` (never committed) locally and on the
deploy VM:

```
DEEPGRAM_API_KEY=<your key>
TEAM_ROSTER=Archit, Avni, Vaibhav, Ravi, Astha, Prakhal, Ayan, Adarsh
```

The extension popup's language dropdown (`en`/`hi`/`hinglish`/`auto`) still
works — mapped onto Deepgram's `language` param (`hinglish`/`auto` both map
to `multi`).

The durable chunk pass and final global pass can each consume transcription
minutes. The chunk output is retained as a recovery fallback if the final
pass times out or the provider is temporarily unavailable.

## CI/CD (`.github/workflows/deploy-vm.yml`)

Pushes to `feature/qdrant-migration-and-gcp-deploy` that touch `backend/`,
`frontend/`, `docker-compose.prod.yml`, or `Caddyfile` trigger an automatic
deploy to the GCP VM (`charcha-ai`, project `charcha-hackathon`).

What it does:

1. SSH into the VM as `archit` using the `CHARCHA_VM_SSH_KEY` secret
2. `git fetch` + `git reset --hard` to the pushed commit
3. Builds `backend` and `frontend` images **sequentially** (not in
   parallel), with `docker builder prune -af` between them — the VM is
   small on disk, and building both at once has exhausted it before
4. `docker compose up -d` to recreate the containers that changed
5. Health-checks the backend from *inside* the docker network
   (`docker compose exec caddy wget ... http://backend:8080/health`, with
   retries) — the backend has no host-published port in prod, only Caddy
   does, so a host-level `curl localhost:8080` never works

Required repo secrets:

- `CHARCHA_VM_SSH_KEY` — private key matching `~/.ssh/charcha-server.pub`,
  which must be authorized on the VM for user `archit`
- `CHARCHA_VM_HOST` — the VM's current static external IP

This workflow is separate from the existing `deploy-backend.yml` /
`deploy-frontend.yml`, which target the old `main`-branch production
deployment on a different host — pushing to this feature branch never
triggers those, and vice versa.

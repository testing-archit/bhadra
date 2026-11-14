# Backend

## Transcription (Gnani Prisma v3.0)

`app/services/transcriber.py` calls Gnani Prisma v3.0 using Auto-LID and
the `codemix` output mode. It is purpose-built for Indian-language meetings,
including Hindi/English code-switching, and keeps Indian-language words in
their native script while preserving English terms.

- **Keyterm prompting** — `TEAM_ROSTER` (backend/.env, comma-separated
  names) and learned vocabulary are passed as Prisma key terms (up to 200).
- **Timestamp preservation** — when Prisma returns timestamped segments, they
  are kept for playback and evidence. Meet captions still identify people by
  name when the recording source provides them.
- **Global final pass** — chunks are stored durably during long meetings, then
  the assembled recording is transcribed once for a coherent final transcript.
- **Human review** — the meeting page exposes confidence diagnostics,
  timestamped playback, full-audio reanalysis, and editable speaker names.

Set the roster in `backend/.env` (never committed) locally and on the
deploy VM:

```
GNANI_API_KEY=<your programme key>
TEAM_ROSTER=Archit, Avni, Vaibhav, Ravi, Astha, Prakhal, Ayan, Adarsh
```

The extension popup's language dropdown (`en`/`hi`/`hinglish`/`auto`) still
works — `hinglish` and `auto` use Prisma Auto-LID, while English and Hindi
send `en-IN` and `hi-IN` respectively.

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

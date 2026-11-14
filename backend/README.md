# Backend

## Transcription (Gnani Prisma v3.0)

`app/services/transcriber.py` calls Gnani Prisma v3.0 using Auto-LID and
the `codemix` output style. It handles Indian-language meetings, including
Hindi/English code-switching. `codemix` keeps spoken Indian-language words
in Latin script.

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
works — `hinglish` and `auto` use Prisma's `indic-auto` code, while English
and Hindi send `en-IN` and `hi-IN` respectively. Browser WebM audio is
converted to OGG/Opus before the Prisma REST request.
Clips up to 28 seconds use REST. Longer recordings are split into 25-second
OGG clips and sent to REST in sequence, then placed on one timeline. Gnani's
Batch queue can delay a complete meeting; short REST clips keep the result
available promptly. Speaker IDs are unique per clip because Prisma numbers
each clip independently; enrolled voice profiles may resolve the same person
across clips.

The durable chunk pass and final global pass can each consume transcription
minutes. The chunk output is retained as a recovery fallback if the final
pass times out or the provider is temporarily unavailable.

## Voice profiles and speaker review

Employees can open `/voice-setup` to record 8–60 seconds of their own speech
and explicitly consent to speaker matching. The server creates a 256-number
voice embedding with a local WeSpeaker ONNX model. Only the encrypted embedding
is stored; the setup audio is discarded. Each person can replace or delete
their profile. Meeting audio remains subject to the normal recording controls.

The Docker image downloads the pinned model during its build. For a local
Python server, run `python scripts/download_speaker_model.py` from `backend/`
and install `requirements.txt`. `GET /api/voice/profile` reports whether the
model is available. Prisma supplies anonymous speaker turns; Charcha compares
those turns only against enrolled, eligible meeting participants. Weak or
ambiguous matches stay unnamed. The meeting review lets a person correct
names; confirming their own speaker turn can improve their profile when that
meeting's audio is still available. Voice matching should be checked on real
team speech before treating its automatic labels as reliable.

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

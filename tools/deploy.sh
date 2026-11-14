#!/usr/bin/env bash
# Deploy to the production VM without interrupting meetings. Run from the
# repo checkout on the VM (~/charcha):
#
#   tools/deploy.sh                    # backend, frontend and notetaker
#   tools/deploy.sh backend frontend   # only these
#   tools/deploy.sh --check            # what's running now; changes nothing
#   SKIP_PULL=1 tools/deploy.sh        # deploy the checkout as it is
#
# GitHub Actions normally does all this. The VM can't fetch from GitHub (the
# org turns deploy keys off), so CI sends it the code; by hand, use SKIP_PULL=1
# with a commit already on the VM.
#
# 1. Pull and build every image first — the running containers keep serving.
# 2. frontend restarts at once: web pages only, never a recording.
# 3. backend waits until no meeting is being processed (transcription, AI
#    notes, uploads) or waiting to be ingested, then gets STOP_SECONDS to
#    finish open requests instead of Docker's 10.
# 4. notetaker waits until it isn't in a meeting (or uploading one), checked
#    again right before the restart.
# A service still busy after MAX_WAIT_MINUTES is skipped, never forced.
# Recordings are safe across backend restarts either way: the notetaker keeps
# them on disk and retries the upload until Charcha accepts it.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE=(docker compose -f docker-compose.prod.yml)
MAX_WAIT_MINUTES="${MAX_WAIT_MINUTES:-240}"
STOP_SECONDS="${STOP_SECONDS:-120}"
POLL_SECONDS=30

log() { echo "[deploy $(date -u +%H:%M:%S)] $*"; }

sql() { "${COMPOSE[@]}" exec -T postgres psql -U charcha charcha -At -c "$1"; }

# The notetaker is in a meeting (each visit is its own meeting_session.py
# process, which also uploads the recording when the meeting ends).
notetaker_busy() {
  docker exec charcha-notetaker-1 pgrep -f meeting_session.py >/dev/null 2>&1
}

# Something the backend is doing that a restart would cut off: a processing
# stage under way, or a visit that left the call and whose recording hasn't
# been ingested yet.
backend_work() {
  sql "select (select count(*) from meeting_processing_stages
               where status in ('running', 'pending') and updated_at > now() - interval '45 minutes')
            + (select count(*) from capture_requests
               where status = 'stopped' and updated_at > now() - interval '30 minutes');" 2>/dev/null || echo 0
}
backend_busy() { [ "$(backend_work)" -gt 0 ]; }

describe() {
  if notetaker_busy; then log "notetaker: IN A MEETING"; else log "notetaker: idle"; fi
  local work; work="$(backend_work)"
  if [ "$work" -gt 0 ]; then log "backend: busy ($work meeting(s) being processed)"; else log "backend: idle"; fi
}

# wait_until_idle <name> <busy-check>: 0 once idle, 1 after MAX_WAIT_MINUTES.
wait_until_idle() {
  local name=$1 check=$2 deadline=$(( $(date +%s) + MAX_WAIT_MINUTES * 60 ))
  while "$check"; do
    if [ "$(date +%s)" -ge "$deadline" ]; then
      log "$name still busy after $MAX_WAIT_MINUTES min — NOT restarting it. Run tools/deploy.sh $name later."
      return 1
    fi
    log "$name is busy — waiting (re-checking every ${POLL_SECONDS}s, up to $MAX_WAIT_MINUTES min)"
    sleep "$POLL_SECONDS"
  done
}

restart() {
  # --no-deps: restarting the frontend must not also recreate the backend
  # (it depends on it) behind the backend's own idle check.
  "${COMPOSE[@]}" up -d --no-build --no-deps --timeout "$STOP_SECONDS" "$1"
  log "$1 restarted"
}

if [ "${1:-}" = "--check" ]; then
  describe
  exit 0
fi

services=("$@")
[ ${#services[@]} -eq 0 ] && services=(backend frontend notetaker)

if [ -z "${SKIP_PULL:-}" ]; then
  log "pulling main"
  # Always main from GitHub, whatever branch the checkout tracks.
  git fetch -q origin main
  if [ "$(git rev-parse --abbrev-ref HEAD)" != "main" ]; then
    git checkout -q main
  fi
  git merge -q --ff-only origin/main
fi
log "at $(git log --oneline -1)"
if [ -n "${SKIP_BUILD:-}" ]; then
  # CI builds the images on GitHub and streams them in (docker load), so
  # this small VM never compiles while it serves meetings.
  log "using images already loaded for ${services[*]}"
else
  log "building ${services[*]} (running containers keep serving)"
  "${COMPOSE[@]}" build "${services[@]}"
fi
describe

skipped=()
has() { local s; for s in "${services[@]}"; do [ "$s" = "$1" ] && return 0; done; return 1; }

has frontend && restart frontend
if has backend; then
  if wait_until_idle backend backend_busy; then restart backend; else skipped+=(backend); fi
fi
if has notetaker; then
  if wait_until_idle notetaker notetaker_busy && ! notetaker_busy; then restart notetaker; else skipped+=(notetaker); fi
fi

docker builder prune -af >/dev/null 2>&1 || true
docker image prune -f >/dev/null 2>&1 || true
log "disk: $(df -h / | tail -1 | awk '{print $4 " free (" $5 " used)"}')"
if [ ${#skipped[@]} -gt 0 ]; then
  log "skipped (still busy): ${skipped[*]}"
  exit 2
fi
log "done"

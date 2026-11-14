"""Sends a finished meeting to the Charcha backend.

Each meeting is first written to its own folder under PENDING_DIR
(metadata.json + audio.webm) and only deleted once the backend accepts it, so
a backend outage or redeploy delays a meeting rather than losing it — the
scheduler retries whatever is still pending.
"""

import json
import logging
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

import config

log = logging.getLogger("uploader")
MAX_ATTEMPTS = 3
# Prisma on a multi-hour recording plus extraction can take many minutes.
UPLOAD_TIMEOUT = httpx.Timeout(1800.0, connect=20.0)


class PermanentUploadError(Exception):
    """The backend rejected the meeting itself — retrying cannot help."""


def _post(folder: Path) -> dict:
    metadata = (folder / "metadata.json").read_text(encoding="utf-8")
    audio_path = folder / "audio.webm"
    files = {"metadata": (None, metadata)}
    if audio_path.exists() and audio_path.stat().st_size > 0:
        files["audio"] = ("meeting.webm", audio_path.read_bytes(), "audio/webm")
    response = httpx.post(
        f"{config.BACKEND_URL}/api/bot/ingest",
        headers={"Authorization": f"Bot {config.require('BOT_API_SECRET')}"},
        files=files,
        timeout=UPLOAD_TIMEOUT,
    )
    if response.status_code in (400, 413, 422):
        raise PermanentUploadError(f"{response.status_code}: {response.text[:300]}")
    response.raise_for_status()
    return response.json()


def upload(folder: Path) -> bool:
    """True once the folder is dealt with (ingested, skipped, or permanently
    rejected and moved aside); False when it should be retried later."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = _post(folder)
            log.info("Uploaded %s: %s %s", folder.name, result.get("status"), result.get("meeting_id", ""))
            shutil.rmtree(folder, ignore_errors=True)
            return True
        except PermanentUploadError as error:
            log.error("Backend rejected %s permanently (%s); moving to failed/", folder.name, error)
            failed = config.STATE_DIR / "failed_uploads"
            failed.mkdir(parents=True, exist_ok=True)
            shutil.move(str(folder), failed / folder.name)
            return True
        except Exception as error:
            log.warning("Upload attempt %d for %s failed: %s", attempt, folder.name, error)
            if attempt < MAX_ATTEMPTS:
                time.sleep(15 * attempt)
    return False


def stage(session_id: str, metadata: dict, audio_path: Path | None) -> Path:
    folder = config.PENDING_DIR / session_id
    folder.mkdir(parents=True, exist_ok=True)
    if audio_path and audio_path.exists():
        shutil.move(str(audio_path), folder / "audio.webm")
    # Written last: a folder with metadata.json is a complete upload.
    tmp = folder / "metadata.json.tmp"
    tmp.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    tmp.replace(folder / "metadata.json")
    return folder


def retry_pending() -> None:
    if not config.PENDING_DIR.is_dir():
        return
    for folder in sorted(config.PENDING_DIR.iterdir()):
        if (folder / "metadata.json").exists():
            upload(folder)


# --- live capture requests ("add the notetaker to this meeting link") -----


def _bot_headers() -> dict:
    return {"Authorization": f"Bot {config.require('BOT_API_SECRET')}"}


def claim_capture_requests(capacity: int, active: int = 0) -> list[dict]:
    """Also the bot's heartbeat: the backend marks the notetaker online on
    every call, even when there is nothing to claim, and shows each
    container's size and load in Admin → Notetaker."""
    response = httpx.post(
        f"{config.BACKEND_URL}/api/bot/capture-requests/claim",
        headers=_bot_headers(),
        json={
            "capacity": max(0, capacity),
            "instance": config.INSTANCE_NAME,
            "max_concurrent": config.MAX_CONCURRENT_MEETINGS,
            "active": active,
            "has_auth": config.AUTH_STATE_PATH.exists(),
            "platforms": ["google_meet", "microsoft_teams"],
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return response.json().get("jobs", [])


def report_capture_event(capture_request_id: str, status: str, detail: str | None = None) -> None:
    """Best effort, a few retries. Every attempt reuses one event id so a
    retry after a lost response is deduplicated by the backend."""
    event = {
        "event_id": f"{capture_request_id}:{status}:{uuid.uuid4().hex}",
        "status": status,
        "detail": (detail or "")[:1900] or None,
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    for attempt in range(3):
        try:
            response = httpx.post(
                f"{config.BACKEND_URL}/api/bot/capture-requests/{capture_request_id}/events",
                headers=_bot_headers(),
                json=event,
                timeout=15.0,
            )
            response.raise_for_status()
            return
        except Exception as error:
            log.warning("Could not report %s for capture %s (attempt %d): %s", status, capture_request_id, attempt + 1, error)
            time.sleep(2 * (attempt + 1))


def capture_state(capture_request_id: str) -> dict | None:
    """{"status", "stop_requested", "scheduled_end"}, or None when Charcha
    can't be reached — which is never a stop signal."""
    try:
        response = httpx.get(
            f"{config.BACKEND_URL}/api/bot/capture-requests/{capture_request_id}",
            headers=_bot_headers(),
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def capture_stop_requested(capture_request_id: str) -> bool:
    state = capture_state(capture_request_id)
    return bool(state and state.get("stop_requested"))


def queue_invite(meeting) -> dict:
    """Ask Charcha to queue a visit for a meeting the notetaker was invited to."""
    response = httpx.post(
        f"{config.BACKEND_URL}/api/bot/invites",
        headers=_bot_headers(),
        json={
            "meet_url": meeting.meet_url,
            "title": meeting.title,
            "organizer_email": meeting.organizer_email,
            "attendees": meeting.attendees,
            "start": meeting.start.isoformat(),
            "end": meeting.end.isoformat(),
            "recurring_event_id": meeting.recurring_event_id,
        },
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def live_answer(question: str, captions: list[dict], capture_request_id: str | None, title: str = "") -> str | None:
    """Asks Charcha a question from the call's chat; None if unreachable."""
    try:
        response = httpx.post(
            f"{config.BACKEND_URL}/api/bot/live-answer",
            headers=_bot_headers(),
            json={"question": question, "captions": captions, "capture_request_id": capture_request_id, "title": title},
            timeout=45,
        )
        response.raise_for_status()
        return str(response.json().get("answer") or "").strip() or None
    except Exception as error:
        log.warning("Live answer failed: %s", error)
        return None

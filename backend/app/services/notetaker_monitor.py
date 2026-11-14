"""What the notetaker fleet is doing, for Admin → Notetaker.

Every notetaker container polls `/api/bot/capture-requests/claim` every few
seconds and says who it is, how many meetings it can hold and how many it is
in; that call is its heartbeat (`service_heartbeats`, one row per instance
plus the shared "notetaker" row the rest of the app reads for online/offline).
Claims use SELECT … FOR UPDATE SKIP LOCKED, so adding capacity is just running
another notetaker container anywhere with the same BOT_API_SECRET.
"""

import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database.models import CAPTURE_ACTIVE_STATUSES, CaptureRequest, CaptureSubscriber, Notification, ServiceHeartbeat, User
from app.services import capture_service

HEARTBEAT = "notetaker"
INSTANCE_PREFIX = "notetaker:"
ONLINE_SECONDS = 180
# Instances silent for longer than this are dropped from the list.
FORGET_INSTANCE_AFTER = datetime.timedelta(days=1)
FAILURE_WINDOW_DAYS = 7
FAILURE_STATUSES = ("denied", "timed_out", "failed")

FAILURE_LABELS = {
    "denied": "Denied by someone in the call",
    "not_admitted": "Nobody admitted it",
    "blocked_by_meet": "Blocked by Google Meet or Teams",
    "signed_out": "Blocked: notetaker signed out of Google",
    "queue_timeout": "Waited too long for a free notetaker",
    "offline": "Notetaker was offline",
    "failed": "Error while joining or recording",
}


def failure_reason(status: str, detail: str | None) -> str:
    """Bucket a finished visit by why it failed, from the status and the
    detail the bot (or expire_unclaimed) wrote."""
    text = (detail or "").lower()
    if "blocked" in text and "signed out" in text:
        return "signed_out"
    if "blocked" in text or "can't join this video call" in text or "can’t join this video call" in text:
        return "blocked_by_meet"
    if status == "denied":
        return "not_admitted" if "nobody admitted" in text or "no one responded" in text else "denied"
    if status == "timed_out":
        if "offline" in text:
            return "offline"
        if "busy" in text or "free notetaker" in text or "queue" in text:
            return "queue_timeout"
        return "not_admitted"
    return "failed"


def _iso(value: datetime.datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _visits(db: AsyncSession, statuses: tuple[str, ...]) -> list[dict]:
    subscribers = (
        select(CaptureSubscriber.capture_request_id, func.count().label("n"))
        .where(CaptureSubscriber.released_at.is_(None))
        .group_by(CaptureSubscriber.capture_request_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(CaptureRequest, User, subscribers.c.n)
            .join(User, User.id == CaptureRequest.user_id)
            .outerjoin(subscribers, subscribers.c.capture_request_id == CaptureRequest.id)
            .where(CaptureRequest.status.in_(statuses))
            .order_by(CaptureRequest.created_at)
        )
    ).all()
    return [
        {
            "id": str(capture.id),
            "title": capture.title or capture.meeting_code,
            "meeting_code": capture.meeting_code,
            "status": capture.status,
            "status_label": capture_service.STATUS_LABELS.get(capture.status, capture.status),
            "status_detail": capture.status_detail,
            "source": capture.source,
            "requested_by": user.name or user.email,
            "subscribers": count or 0,
            "created_at": _iso(capture.created_at),
            "claimed_at": _iso(capture.claimed_at),
            "scheduled_start": _iso(capture.scheduled_start),
            "scheduled_end": _iso(capture.scheduled_end),
        }
        for capture, user, count in rows
    ]


async def overview(db: AsyncSession) -> dict:
    now = datetime.datetime.now(datetime.UTC)
    beats = (
        await db.execute(
            select(ServiceHeartbeat).where(
                (ServiceHeartbeat.name == HEARTBEAT) | ServiceHeartbeat.name.startswith(INSTANCE_PREFIX)
            )
        )
    ).scalars().all()
    shared = next((b for b in beats if b.name == HEARTBEAT), None)
    instances = []
    for beat in beats:
        if beat.name == HEARTBEAT or now - beat.last_seen_at > FORGET_INSTANCE_AFTER:
            continue
        detail = beat.detail or {}
        instances.append(
            {
                "name": beat.name.removeprefix(INSTANCE_PREFIX),
                "last_seen_at": _iso(beat.last_seen_at),
                "online": (now - beat.last_seen_at).total_seconds() < ONLINE_SECONDS,
                "max_concurrent": detail.get("max_concurrent"),
                "active": detail.get("active"),
                "free": detail.get("capacity"),
                "signed_in": detail.get("has_auth"),
            }
        )
    instances.sort(key=lambda item: item["name"])
    online = [item for item in instances if item["online"]]
    capacity = {
        "total": sum(item["max_concurrent"] or 0 for item in online),
        "active": sum(item["active"] or 0 for item in online),
        "free": sum(item["free"] or 0 for item in online),
        # A notetaker too old to report its size only says how much is free.
        "known": all(item["max_concurrent"] is not None for item in online),
    }

    live = await _visits(db, tuple(s for s in CAPTURE_ACTIVE_STATUSES if s != "requested"))
    queued = await _visits(db, ("requested",))

    since = now - datetime.timedelta(days=FAILURE_WINDOW_DAYS)
    failed = (
        await db.execute(
            select(CaptureRequest)
            .where(CaptureRequest.status.in_(FAILURE_STATUSES), CaptureRequest.updated_at >= since)
            .order_by(CaptureRequest.updated_at.desc())
        )
    ).scalars().all()
    groups: dict[str, dict] = {}
    for capture in failed:
        reason = failure_reason(capture.status, capture.status_detail)
        group = groups.setdefault(
            reason,
            {"reason": reason, "label": FAILURE_LABELS[reason], "count": 0, "last_at": _iso(capture.updated_at), "example": capture.status_detail},
        )
        group["count"] += 1
    attempts = await db.scalar(
        select(func.count()).select_from(CaptureRequest).where(
            CaptureRequest.created_at >= since, CaptureRequest.status != "cancelled"
        )
    )
    return {
        "online": bool(shared and (now - shared.last_seen_at).total_seconds() < ONLINE_SECONDS),
        "last_heartbeat_at": _iso(shared.last_seen_at) if shared else None,
        "instances": instances,
        "capacity": capacity,
        "live": live,
        "queued": queued,
        "queue_length": len(queued),
        "failures": {
            "days": FAILURE_WINDOW_DAYS,
            "total": len(failed),
            "visits": attempts or 0,
            "groups": sorted(groups.values(), key=lambda g: g["count"], reverse=True),
            "recent": [
                {
                    "id": str(c.id), "title": c.title or c.meeting_code, "status": c.status,
                    "reason": failure_reason(c.status, c.status_detail), "detail": c.status_detail, "at": _iso(c.updated_at),
                }
                for c in failed[:10]
            ],
        },
    }


SIGNED_OUT_ALERT = "notetaker_signed_out"
SIGNED_OUT_ALERT_EVERY = datetime.timedelta(hours=12)


async def alert_if_signed_out(db: AsyncSession, status: str, detail: str | None) -> int:
    """The notetaker's Google login expired: Meet now refuses it ("You can't
    join this video call") at every meeting that only admits signed-in
    accounts. Tell every admin, at most once per SIGNED_OUT_ALERT_EVERY.
    Returns how many were told; the caller commits."""
    if failure_reason(status, detail) != "signed_out":
        return 0
    since = datetime.datetime.now(datetime.UTC) - SIGNED_OUT_ALERT_EVERY
    recent = await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.type == SIGNED_OUT_ALERT, Notification.created_at >= since
        )
    )
    if recent:
        return 0
    admins = (
        await db.execute(
            select(User).where(
                User.status == "active",
                or_(User.role.in_(("admin", "super_admin")), func.lower(User.email).in_([e.lower() for e in settings.admin_email_list])),
            )
        )
    ).scalars().all()
    for admin in admins:
        db.add(
            Notification(
                user_id=admin.id,
                type=SIGNED_OUT_ALERT,
                message=(
                    "The notetaker is signed out of Google, so Meet is turning it away. Sign it back in "
                    "(backend/bot/README.md, step 3) to keep recording meetings."
                ),
                link="/admin?tab=notetaker",
            )
        )
    return len(admins)

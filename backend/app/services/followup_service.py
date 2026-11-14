"""After a meeting's notes are ready: tell each colleague what they were given.

A task's `owner_user_id` is only set when the stated owner resolved
unambiguously (insight_service), so a notification never goes to a guess.
Only owners who were in the meeting are told; tasks for anyone else wait for
the recorder or organizer (privacy_service.notify_held). Each person is told once per meeting — reprocessing a
meeting doesn't repeat it.
"""

import logging
import uuid
from collections import defaultdict

from sqlalchemy import select

from app.database.db import async_session
from app.database.models import Meeting, MeetingAttendee, MeetingTask, Notification, User
from app.services import email_service, privacy_service

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "tasks_assigned"


async def notify_task_owners(meeting_id: uuid.UUID) -> int:
    """Returns how many people were notified. Never raises — it runs as a
    background step after processing, where a failure must not surface."""
    try:
        async with async_session() as db:
            meeting = await db.get(Meeting, meeting_id)
            if meeting is None or meeting.deleted_at is not None:
                return 0
            tasks = (
                await db.execute(
                    select(MeetingTask).where(
                        MeetingTask.meeting_id == meeting_id,
                        MeetingTask.owner_user_id.isnot(None),
                        MeetingTask.deleted_at.is_(None),
                        MeetingTask.status != "done",
                    )
                )
            ).scalars().all()
            # An owner who wasn't in the meeting hears nothing until the
            # recorder or organizer sends them the task (privacy_service).
            inside = await privacy_service.owners_in_meeting(db, tasks)
            access = {task.id: privacy_service.owner_access(task, inside) for task in tasks}
            await privacy_service.notify_held(db, meeting, [t for t in tasks if access[t.id] == "held"])
            by_owner: dict[uuid.UUID, int] = defaultdict(int)
            for task in tasks:
                if access[task.id] == "meeting":
                    by_owner[task.owner_user_id] += 1
            if not by_owner:
                await db.commit()
                return 0
            already = set(
                (
                    await db.execute(
                        select(Notification.user_id).where(
                            Notification.type == NOTIFICATION_TYPE,
                            Notification.user_id.in_(by_owner),
                            Notification.link.contains(str(meeting_id)),
                        )
                    )
                ).scalars().all()
            )
            sent = 0
            for owner_id, count in by_owner.items():
                if owner_id in already:
                    continue
                owner = await db.get(User, owner_id)
                if owner is None or owner.status != "active":
                    continue
                db.add(
                    Notification(
                        user_id=owner_id,
                        type=NOTIFICATION_TYPE,
                        message=f'You were given {count} task{"s" if count != 1 else ""} in "{meeting.title}"',
                        link=f"/meetings/{meeting_id}?tab=actions",
                    )
                )
                sent += 1
            await db.commit()
            return sent
    except Exception:
        logger.exception("Could not notify task owners for meeting %s", meeting_id)
        return 0


# Meetings whose notes arrive later, when nobody is looking at the screen.
ANNOUNCED_SOURCES = {"bot", "capture", "upload"}


async def announce_notes(meeting_id: uuid.UUID) -> int:
    """Email "notes ready" once per meeting to everyone with granted access
    and the recorder: one email, To the organizer (else the recorder) with
    the others in CC, so everyone sees who got it. Their tasks are in it,
    so the separate tasks email is skipped for them. Never raises."""
    try:
        async with async_session() as db:
            meeting = await db.get(Meeting, meeting_id)
            if meeting is None or meeting.deleted_at is not None or meeting.source not in ANNOUNCED_SOURCES:
                return 0
            people = set(
                (
                    await db.execute(
                        select(MeetingAttendee.user_id).where(
                            MeetingAttendee.meeting_id == meeting_id,
                            MeetingAttendee.user_id.isnot(None),
                            MeetingAttendee.access == "granted",
                        )
                    )
                ).scalars().all()
            ) | {meeting.user_id}
            people.discard(None)
            if not people:
                return 0
            to = meeting.organizer_user_id if meeting.organizer_user_id in people else meeting.user_id
            if to not in people:
                to = sorted(people, key=str)[0]
            cc = sorted((p for p in people if p != to), key=str)
            await email_service.enqueue(
                db, "notes_ready", to, {"meeting_id": str(meeting_id), "cc": [str(p) for p in cc]},
                dedupe_key=f"notes_ready:{meeting_id}",
            )
            await db.commit()
            return len(people)
    except Exception:
        logger.exception("Could not queue notes-ready emails for meeting %s", meeting_id)
        return 0

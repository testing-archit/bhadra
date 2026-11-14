"""What stays inside a meeting.

Two rules, on top of invite-based meeting access (app/dependencies.py):

* **Tasks for people who weren't in the meeting are held.** A task whose
  owner can't open its meeting (not the recorder, not a granted attendee) is
  invisible to that owner — no Tasks page, notification, email or Jira —
  until the recorder or organizer sends it (`share_task`). Sending shares the
  task alone: the owner never sees the meeting's title, transcript or quotes.
  The managers are told when a meeting has held tasks (`notify_held`).
  "Two founders decide to let Archit go and give Avni his work" must not
  reach Avni's task list on its own.
* **Confidential meetings** (`set_confidential`): marked by a person or by
  the notes AI, which flags personnel, pay, legal and deal talk at no extra
  cost. Only the people in the meeting can open one — Charcha admins too lose
  their exemption — and it never goes to Jira or a public share link.
"""

import datetime
import uuid

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Meeting, MeetingAttendee, MeetingTask, Notification
from app.dependencies import meeting_visibility_clause

HELD_NOTIFICATION = "tasks_held"


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def task_visibility_clause(user):
    """Tasks `user` may see: everything in meetings they can open, plus
    tasks that were sent to them from meetings they can't."""
    return or_(
        meeting_visibility_clause(user),
        and_(MeetingTask.owner_user_id == user.id, MeetingTask.owner_shared_at.isnot(None)),
    )


async def owners_in_meeting(db: AsyncSession, tasks: list[MeetingTask]) -> set[tuple[uuid.UUID, uuid.UUID]]:
    """(meeting id, owner id) pairs where the task's owner can open the
    meeting as a participant — the recorder or a granted attendee. An admin's
    exemption doesn't count: an admin who wasn't there is an outsider too."""
    pairs = {(t.meeting_id, t.owner_user_id) for t in tasks if t.owner_user_id}
    if not pairs:
        return set()
    meeting_ids = {m for m, _ in pairs}
    user_ids = {u for _, u in pairs}
    inside = set(
        (await db.execute(
            select(MeetingAttendee.meeting_id, MeetingAttendee.user_id).where(
                MeetingAttendee.meeting_id.in_(meeting_ids), MeetingAttendee.user_id.in_(user_ids),
                MeetingAttendee.access == "granted",
            )
        )).all()
    )
    inside |= set((await db.execute(select(Meeting.id, Meeting.user_id).where(Meeting.id.in_(meeting_ids)))).all())
    return {(m, u) for m, u in inside} & pairs


def owner_access(task: MeetingTask, inside: set[tuple[uuid.UUID, uuid.UUID]]) -> str | None:
    """How the task's owner sees it: "meeting" (they were in it), "shared"
    (sent to them), "private" (a manager kept it from them), "held" (waiting
    for that decision), or None when it has no owner account."""
    if task.owner_user_id is None:
        return None
    if (task.meeting_id, task.owner_user_id) in inside:
        return "meeting"
    if task.owner_shared_at is not None:
        return "shared"
    if task.owner_kept_private_at is not None:
        return "private"
    return "held"


async def is_held(db: AsyncSession, task: MeetingTask) -> bool:
    return owner_access(task, await owners_in_meeting(db, [task])) == "held"


def share_task(db: AsyncSession, task: MeetingTask) -> None:
    """Send the task (only the task) to an owner who wasn't in the meeting."""
    task.owner_shared_at = _now()
    task.owner_kept_private_at = None
    db.add(Notification(
        user_id=task.owner_user_id, type="task_assigned",
        message=f'You were given a task: "{task.description}"', link=f"/tasks?task={task.id}",
    ))


def keep_private(task: MeetingTask) -> None:
    task.owner_kept_private_at = _now()
    task.owner_shared_at = None


async def notify_held(db: AsyncSession, meeting: Meeting, held: list[MeetingTask]) -> int:
    """Tell the recorder and organizer, once per meeting, that some tasks are
    for people who weren't in it and wait for their decision."""
    if not held:
        return 0
    managers = {meeting.user_id, meeting.organizer_user_id} - {None}
    link = f"/meetings/{meeting.id}?tab=actions"
    already = set((await db.execute(
        select(Notification.user_id).where(
            Notification.type == HELD_NOTIFICATION, Notification.user_id.in_(managers), Notification.link == link
        )
    )).scalars().all())
    count = len(held)
    for manager in managers - already:
        db.add(Notification(
            user_id=manager, type=HELD_NOTIFICATION, link=link,
            message=(
                f'{count} task{"s" if count != 1 else ""} in "{meeting.title}" '
                f'{"are" if count != 1 else "is"} for people who weren\'t in the meeting. '
                "They won't see them unless you send them."
            ),
        ))
    return len(managers - already)


async def set_confidential(db: AsyncSession, meeting: Meeting, confidential: bool, *, source: str, reason: str | None = None) -> None:
    """Mark or unmark. Marking also turns off the public share link and takes
    back access that came only from Jira."""
    meeting.confidential = confidential
    meeting.confidential_source = source
    meeting.confidential_reason = (reason or "").strip()[:120] or None if confidential else None
    if confidential:
        meeting.share_token = None
        await db.execute(delete(MeetingAttendee).where(MeetingAttendee.meeting_id == meeting.id, MeetingAttendee.source == "jira"))


async def apply_ai_flag(db: AsyncSession, meeting: Meeting, extraction: dict) -> None:
    """The notes AI's sensitivity call. It can only mark: a person's choice
    (either way) stands, and a meeting it marked before stays marked."""
    if meeting.confidential_source == "manual" or meeting.confidential:
        return
    if extraction.get("confidential"):
        await set_confidential(db, meeting, True, source="ai", reason=extraction.get("confidentialReason"))

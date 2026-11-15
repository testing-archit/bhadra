import datetime
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import get_db
from app.database.models import Meeting, MeetingTask, Notification, Project, TaskComment, TaskHistory, TaskLink, User
from app.dependencies import get_current_user, meeting_visibility_clause, user_can_manage_meeting_access
from app.services import insight_service, jira_service, privacy_service, vocabulary_service
from app.services.meeting_index_service import rebuild_meeting_index

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)

# Manually added tasks still need a meeting_id to satisfy the FK and to keep
# department scoping (which joins through Meeting) working unchanged. Each
# user gets a single reused placeholder meeting to hold their manual tasks
# rather than a real meeting record per task.
# jira_service.MANUAL_TASKS_MEETING_TITLE must match: those placeholder
# meetings are never opened to the Jira team.
MANUAL_TASKS_MEETING_TITLE = "Manually Added Tasks"

TRACKED_FIELDS = ("status", "description", "owner", "deadline", "due_date", "priority")
LINK_TYPES = {"blocks", "blocked_by", "depends_on", "relates_to"}
_INVERSE_LINK = {"blocks": "blocked_by", "blocked_by": "blocks"}


def _task_visibility(user: User):
    """Tasks in meetings this person can open, plus tasks sent to them from
    meetings they weren't in (privacy_service). A task that merely names
    them, from a meeting they weren't in, stays out of sight until then."""
    return privacy_service.task_visibility_clause(user)


class TaskUpdate(BaseModel):
    status: str | None = None
    description: str | None = None
    owner: str | None = None
    deadline: str | None = None
    due_date: datetime.date | None = None
    clear_due_date: bool = False
    priority: str | None = None


class TaskCreate(BaseModel):
    description: str
    owner: str | None = None
    deadline: str | None = None
    due_date: datetime.date | None = None
    priority: str | None = None
    parent_task_id: uuid.UUID | None = None


class CommentCreate(BaseModel):
    body: str


class LinkCreate(BaseModel):
    linked_task_id: uuid.UUID
    link_type: str


def _owner_keys(user: User) -> set[str]:
    """What a transcript might call this person: email, its local part, full
    name, first name (matches the web client's isMine)."""
    email = user.email.strip().lower()
    keys = {email, email.split("@")[0]}
    if user.name and user.name.strip():
        name = user.name.strip().lower()
        keys |= {name, name.split()[0]}
    return keys


def _relation(task: MeetingTask, user: User, meeting_user_id, organizer_user_id) -> dict:
    """Whose task this is from the viewer's side: `mine` (they own it),
    `delegated` (it came out of a meeting they recorded or organised, or
    they added it, and someone else owns it — they're waiting on it)."""
    mine = task.owner_user_id == user.id or (task.owner or "").strip().lower() in _owner_keys(user)
    from_my_meeting = user.id in {meeting_user_id, organizer_user_id}
    return {"mine": mine, "delegated": from_my_meeting and not mine and bool((task.owner or "").strip())}


HIDDEN_MEETING_TITLE = "A meeting you weren't in"


def _serialize(
    task: MeetingTask, title: str, date: datetime.datetime, project_name: str | None, relation: dict | None = None,
    *, owner_access: str | None = None, meeting_hidden: bool = False,
) -> dict:
    return {
        "id": str(task.id),
        "meeting_id": str(task.meeting_id),
        # Sent from a meeting the viewer wasn't in: the task, not the meeting.
        "meeting_title": HIDDEN_MEETING_TITLE if meeting_hidden else title,
        "meeting_hidden": meeting_hidden,
        # "meeting" | "shared" | "private" | "held" | None — see privacy_service.owner_access.
        "owner_access": owner_access,
        "meeting_date": date.isoformat(),
        "owner": task.owner,
        "description": task.description,
        "deadline": task.deadline,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "priority": task.priority,
        "status": task.status,
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "updated_at": task.updated_at.isoformat(),
        "verified_at": task.verified_at.isoformat() if task.verified_at else None,
        "project": project_name,
        "project_id": str(task.project_id) if task.project_id else None,
        "jira_issue_key": task.jira_issue_key,
        "jira_status": task.jira_status,
        "jira_error": task.jira_error,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "origin": task.origin,
        "mine": False,
        "delegated": False,
        **(relation or {}),
    }


async def _hand_to_owner(db: AsyncSession, task: MeetingTask, meeting: Meeting, actor: User) -> None:
    """Someone gave this task to a person. If that person was in the meeting
    they're told, with the meeting. If not, they get the task alone — giving
    it was deliberate — except from a confidential meeting, where it waits
    for the recorder or organizer to send it (privacy_service)."""
    task.owner_shared_at = task.owner_kept_private_at = None
    if task.owner_user_id is None or task.owner_user_id == actor.id:
        return
    access = privacy_service.owner_access(task, await privacy_service.owners_in_meeting(db, [task]))
    if access == "meeting":
        db.add(
            Notification(
                user_id=task.owner_user_id,
                type="task_assigned",
                message=f'You were assigned: "{task.description}"',
                link=f"/meetings/{task.meeting_id}#task-{task.id}",
            )
        )
    elif not meeting.confidential:
        privacy_service.share_task(db, task)
    else:
        await privacy_service.notify_held(db, meeting, [task])


async def _create_due_soon_notifications(db: AsyncSession, tasks: list[MeetingTask]) -> None:
    """Lazily generated on read rather than via a scheduler (no cron/Celery
    in this stack) — called from list_tasks, so any active user browsing
    tasks triggers the check. At most one "due soon" notification per task
    per day, regardless of how many times this runs."""
    today = datetime.date.today()
    due_soon = [
        t for t in tasks
        if t.due_date and t.status != "done" and t.owner_user_id and t.due_date <= today + datetime.timedelta(days=1)
    ]
    if not due_soon:
        return
    # Only owners who can see the task: in the meeting, or sent it.
    inside = await privacy_service.owners_in_meeting(db, due_soon)
    access = {t.id: privacy_service.owner_access(t, inside) for t in due_soon}
    due_soon = [t for t in due_soon if access[t.id] in ("meeting", "shared")]
    if not due_soon:
        return

    def link_for(task: MeetingTask) -> str:
        return f"/meetings/{task.meeting_id}#task-{task.id}" if access[task.id] == "meeting" else f"/tasks?task={task.id}"

    since = datetime.datetime.now(datetime.UTC) - datetime.timedelta(hours=20)
    result = await db.execute(
        select(Notification.link).where(
            Notification.type == "task_due_soon",
            Notification.created_at >= since,
            Notification.link.in_([link_for(t) for t in due_soon]),
        )
    )
    already_notified_links = {row[0] for row in result.all()}
    for task in due_soon:
        link = link_for(task)
        if link in already_notified_links:
            continue
        user = await db.get(User, task.owner_user_id)
        if user is None or user.status != "active":
            continue
        label = "overdue" if task.due_date < today else "due today" if task.due_date == today else "due tomorrow"
        db.add(
            Notification(
                user_id=user.id,
                type="task_due_soon",
                message=f'Task {label}: "{task.description}"',
                link=link,
            )
        )


@router.get("")
async def list_tasks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    query = (
        select(MeetingTask, Meeting.title, Meeting.date, Project.name, Meeting.user_id, Meeting.organizer_user_id)
        .join(Meeting, MeetingTask.meeting_id == Meeting.id)
        .outerjoin(Project, and_(MeetingTask.project_id == Project.id, Project.deleted_at.is_(None)))
        .where(MeetingTask.deleted_at.is_(None), Meeting.deleted_at.is_(None))
        .order_by(MeetingTask.created_at.desc())
        .where(_task_visibility(user))
    )

    result = await db.execute(query)
    rows = result.all()
    try:
        await _create_due_soon_notifications(db, [row[0] for row in rows])
        await db.commit()
    except Exception:
        # Best-effort only — never let a notification hiccup break the task
        # list. Deliberately no rollback(): that would expire every task
        # object already loaded above, and re-reading their attributes for
        # _serialize() below would then try (and fail) to lazy-load them
        # outside a greenlet context. Any pending notification INSERTs are
        # simply dropped when this request-scoped session closes.
        logger.exception("Could not create due-soon notifications")
    tasks = [row[0] for row in rows]
    inside = await privacy_service.owners_in_meeting(db, tasks)
    readable = await _readable_meetings(db, user, {task.meeting_id for task in tasks})
    return [
        _serialize(
            task, title, date, project_name, _relation(task, user, meeting_user_id, organizer_user_id),
            owner_access=privacy_service.owner_access(task, inside), meeting_hidden=task.meeting_id not in readable,
        )
        for task, title, date, project_name, meeting_user_id, organizer_user_id in rows
    ]


async def _readable_meetings(db: AsyncSession, user: User, meeting_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    if not meeting_ids:
        return set()
    return set((await db.execute(
        select(Meeting.id).where(Meeting.id.in_(meeting_ids), meeting_visibility_clause(user))
    )).scalars().all())


@router.post("")
async def create_task(
    body: TaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not body.description.strip():
        raise HTTPException(status_code=400, detail="Description is required")

    if body.parent_task_id:
        try:
            await _get_owned_task(body.parent_task_id, user, db)
        except HTTPException:
            raise HTTPException(status_code=404, detail="Parent task not found")
    task, meeting = await add_manual_task(
        db, user, owner=body.owner, description=body.description, deadline=body.deadline,
        due_date=body.due_date, priority=body.priority, parent_task_id=body.parent_task_id,
    )
    return _serialize(task, meeting.title, meeting.date, None, _relation(task, user, meeting.user_id, None))


async def add_manual_task(db: AsyncSession, user: User, *, owner: str | None, description: str, deadline: str | None = None,
                          due_date=None, priority: str | None = None, parent_task_id=None, origin: str = "manual", task_id: uuid.UUID | None = None):
    """A task outside any meeting (Tasks page, or said to Wilco Live), filed
    in the person's own manual-tasks meeting and handed to its owner."""
    meeting = (await db.execute(select(Meeting).where(
        Meeting.user_id == user.id, Meeting.title == MANUAL_TASKS_MEETING_TITLE, Meeting.deleted_at.is_(None),
    ))).scalar_one_or_none()
    if meeting is None:
        meeting = Meeting(user_id=user.id, title=MANUAL_TASKS_MEETING_TITLE, date=datetime.datetime.now(datetime.UTC),
                          duration_minutes=0, department=user.department)
        db.add(meeting)
        await db.flush()
    task = MeetingTask(
        **({"id": task_id} if task_id else {}),
        meeting_id=meeting.id, owner=owner or None, description=description.strip(), deadline=deadline or None,
        due_date=due_date, priority=priority or None, parent_task_id=parent_task_id, origin=origin,
        owner_user_id=await insight_service.resolve_owner_user_id(db, meeting.id, owner),
    )
    db.add(task)
    await db.flush()
    await _hand_to_owner(db, task, meeting, user)
    await db.commit()
    await db.refresh(task)
    return task, meeting


async def _get_owned_task(
    task_id: uuid.UUID, user: User, db: AsyncSession, *, include_own: bool = True
) -> tuple[MeetingTask, str | None]:
    query = (
        select(MeetingTask, Meeting.department)
        .join(Meeting, MeetingTask.meeting_id == Meeting.id)
        .where(
            MeetingTask.id == task_id,
            MeetingTask.deleted_at.is_(None),
            Meeting.deleted_at.is_(None),
            _task_visibility(user) if include_own else meeting_visibility_clause(user),
        )
    )
    row = (await db.execute(query)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")
    task, task_department = row
    return task, task_department


class BulkDelete(BaseModel):
    ids: list[uuid.UUID]


MAX_BULK_DELETE = 200


@router.post("/delete")
async def delete_tasks(
    body: BulkDelete,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Move several tasks to the Recycle Bin at once. Same rule as deleting
    one: you must be able to read each task's meeting. Ones you can't are
    reported, not deleted."""
    if len(body.ids) > MAX_BULK_DELETE:
        raise HTTPException(status_code=422, detail=f"Delete at most {MAX_BULK_DELETE} tasks at a time")
    now = datetime.datetime.now(datetime.UTC)
    deleted: list[str] = []
    failed: dict[str, str] = {}
    meetings: set[uuid.UUID] = set()
    for task_id in dict.fromkeys(body.ids):
        try:
            task, _ = await _get_owned_task(task_id, user, db, include_own=False)
        except HTTPException:
            failed[str(task_id)] = "Not found, or you can't open its meeting"
            continue
        task.deleted_at = now
        task.deleted_by = user.id
        meetings.add(task.meeting_id)
        deleted.append(str(task_id))
    await db.flush()
    for meeting_id in meetings:
        await rebuild_meeting_index(db, meeting_id)
    await db.commit()
    return {"deleted": deleted, "failed": failed}


@router.delete("/{task_id}")
async def delete_task(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    # Deleting removes it for everyone in the meeting, so being its owner
    # isn't enough — you need to be able to read the meeting.
    task, _ = await _get_owned_task(task_id, user, db, include_own=False)
    meeting_id = task.meeting_id
    task.deleted_at = datetime.datetime.now(datetime.UTC)
    task.deleted_by = user.id
    await db.flush()
    await rebuild_meeting_index(db, meeting_id)
    await db.commit()
    return {"ok": True}


@router.patch("/{task_id}")
async def update_task(
    task_id: uuid.UUID,
    body: TaskUpdate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    task, _ = await _get_owned_task(task_id, user, db)

    previous_owner = task.owner
    previous_description = task.description
    changed_fields: set[str] = set()
    updates: dict[str, object | None] = {
        field: getattr(body, field) for field in TRACKED_FIELDS if getattr(body, field, None) is not None
    }
    if body.clear_due_date:
        updates["due_date"] = None

    for field, value in updates.items():
        old_value = getattr(task, field)
        if old_value == value:
            continue
        changed_fields.add(field)
        db.add(
            TaskHistory(
                task_id=task.id,
                changed_by=user.id,
                field=field,
                old_value=str(old_value) if old_value is not None else None,
                new_value=str(value) if value is not None else None,
            )
        )
        setattr(task, field, value)

    if not task.description.strip():
        raise HTTPException(status_code=422, detail="Task description is required")

    if task.owner != previous_owner:
        # Reassigning moves the task to the new person's account too;
        # otherwise it keeps counting as the previous owner's task.
        task.owner_user_id = await insight_service.resolve_owner_user_id(db, task.meeting_id, task.owner)
    if task.owner != previous_owner:
        await _hand_to_owner(db, task, await db.get(Meeting, task.meeting_id), user)

    task.verified_at = datetime.datetime.now(datetime.UTC)
    task.verified_by = user.id

    await db.flush()
    # A fixed mishearing ("Ras" → "Raj") is fixed across the meeting and learned.
    corrections, propagation = ([], None)
    if "description" in changed_fields:
        corrections, propagation = await vocabulary_service.correct_from_edit(
            db, task.meeting_id, [(previous_description, task.description)], user
        )
    await rebuild_meeting_index(db, task.meeting_id)
    await db.commit()
    if propagation is not None:
        vocabulary_service.schedule_followups(background_tasks, task.meeting_id, propagation)
    if task.jira_issue_key and changed_fields:
        # Keep the Jira issue in step; Jira being slow or down mustn't fail
        # the edit (failures show on the task as jira_error).
        background_tasks.add_task(jira_service.push_changes, task.id, changed_fields)
    # updated_at is a server-computed onupdate column — SQLAlchemy expires it
    # after the UPDATE regardless of expire_on_commit, so it must be reloaded
    # via an explicit await before being read, or a sync attribute access
    # would try (and fail) to lazy-load it outside a greenlet context.
    await db.refresh(task)
    return {
        "id": str(task.id),
        "description": task.description,
        "owner": task.owner,
        "deadline": task.deadline,
        "due_date": task.due_date.isoformat() if task.due_date else None,
        "priority": task.priority,
        "status": task.status,
        "parent_task_id": str(task.parent_task_id) if task.parent_task_id else None,
        "updated_at": task.updated_at.isoformat(),
        "verified_at": task.verified_at.isoformat() if task.verified_at else None,
        "jira_issue_key": task.jira_issue_key,
        "jira_status": task.jira_status,
        "jira_error": task.jira_error,
        "learned_corrections": corrections,
    }


class OwnerAccess(BaseModel):
    action: str  # "send" | "keep_private"


@router.post("/{task_id}/owner-access")
async def set_owner_access(
    task_id: uuid.UUID,
    body: OwnerAccess,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The recorder or organizer decides whether a task's owner, who wasn't
    in the meeting, gets it. Sending shares the task only, never the meeting."""
    task, _ = await _get_owned_task(task_id, user, db, include_own=False)
    meeting = await db.get(Meeting, task.meeting_id)
    if not await user_can_manage_meeting_access(db, user, meeting):
        raise HTTPException(status_code=403, detail="Only the person who recorded or organised this meeting can decide this")
    if body.action not in ("send", "keep_private"):
        raise HTTPException(status_code=422, detail="action must be send or keep_private")
    access = privacy_service.owner_access(task, await privacy_service.owners_in_meeting(db, [task]))
    if access in (None, "meeting"):
        raise HTTPException(status_code=409, detail="This task's owner was in the meeting, or isn't a Wilco account")
    if body.action == "send":
        if access != "shared":
            privacy_service.share_task(db, task)
    else:
        privacy_service.keep_private(task)
    await db.commit()
    return {"id": str(task.id), "owner_access": "shared" if body.action == "send" else "private"}


@router.post("/{task_id}/jira")
async def send_task_to_jira(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create the Jira issue for this task (idempotent)."""
    task, _ = await _get_owned_task(task_id, user, db)
    try:
        key = await jira_service.create_issue(db, task)
    except jira_service.JiraError as error:
        raise HTTPException(status_code=502, detail=str(error))
    return {"id": str(task.id), "jira_issue_key": key, "jira_status": task.jira_status}


@router.get("/{task_id}/comments")
async def list_comments(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_owned_task(task_id, user, db)
    result = await db.execute(
        select(TaskComment, User.name, User.email)
        .outerjoin(User, TaskComment.user_id == User.id)
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at.asc())
    )
    return [
        {
            "id": str(comment.id),
            "body": comment.body,
            # Written in Jira by someone not linked to a Wilco account.
            "author": name or email or comment.author_name or "Former teammate",
            "source": comment.source,
            "created_at": comment.created_at.isoformat(),
        }
        for comment, name, email in result.all()
    ]


@router.post("/{task_id}/comments")
async def add_comment(
    task_id: uuid.UUID,
    body: CommentCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not body.body.strip():
        raise HTTPException(status_code=400, detail="Comment cannot be empty")
    task, _ = await _get_owned_task(task_id, user, db)
    comment = TaskComment(task_id=task_id, user_id=user.id, body=body.body.strip())
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    if task.jira_issue_key:
        background_tasks.add_task(jira_service.push_comment, comment.id)
    return {
        "id": str(comment.id),
        "body": comment.body,
        "author": user.name or user.email,
        "source": None,
        "created_at": comment.created_at.isoformat(),
    }


@router.get("/{task_id}/history")
async def get_history(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_owned_task(task_id, user, db)
    result = await db.execute(
        select(TaskHistory, User.name, User.email)
        .outerjoin(User, TaskHistory.changed_by == User.id)
        .where(TaskHistory.task_id == task_id)
        .order_by(TaskHistory.changed_at.desc())
    )
    return [
        {
            "id": str(entry.id),
            "field": entry.field,
            "old_value": entry.old_value,
            "new_value": entry.new_value,
            "changed_by": "Jira" if entry.source == "jira" else name or email or (
                # A learned correction Wilco applied by itself has no person.
                "Wilco" if entry.source == "vocabulary" and entry.changed_by is None else "Former teammate"
            ),
            "changed_at": entry.changed_at.isoformat(),
        }
        for entry, name, email in result.all()
    ]


@router.get("/{task_id}/links")
async def list_links(
    task_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _get_owned_task(task_id, user, db)
    result = await db.execute(
        select(TaskLink, MeetingTask.description, MeetingTask.status)
        .join(MeetingTask, TaskLink.linked_task_id == MeetingTask.id)
        .join(Meeting, MeetingTask.meeting_id == Meeting.id)
        # Someone else may have linked a task this person can't see.
        .where(TaskLink.task_id == task_id, MeetingTask.deleted_at.is_(None), Meeting.deleted_at.is_(None), _task_visibility(user))
    )
    return [
        {
            "id": str(link.id),
            "link_type": link.link_type,
            "linked_task_id": str(link.linked_task_id),
            "linked_task_description": description,
            "linked_task_status": status,
        }
        for link, description, status in result.all()
    ]


@router.post("/{task_id}/links")
async def create_link(
    task_id: uuid.UUID,
    body: LinkCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if body.link_type not in LINK_TYPES:
        raise HTTPException(status_code=400, detail=f"link_type must be one of {sorted(LINK_TYPES)}")
    if body.linked_task_id == task_id:
        raise HTTPException(status_code=400, detail="A task cannot link to itself")
    await _get_owned_task(task_id, user, db)
    await _get_owned_task(body.linked_task_id, user, db)

    link = TaskLink(task_id=task_id, linked_task_id=body.linked_task_id, link_type=body.link_type)
    db.add(link)
    inverse_type = _INVERSE_LINK.get(body.link_type)
    if inverse_type:
        db.add(TaskLink(task_id=body.linked_task_id, linked_task_id=task_id, link_type=inverse_type))
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=409, detail="This link already exists")
    return {"ok": True}


@router.delete("/{task_id}/links/{link_id}")
async def delete_link(
    task_id: uuid.UUID,
    link_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _get_owned_task(task_id, user, db)
    link = await db.get(TaskLink, link_id)
    if link is None or link.task_id != task_id:
        raise HTTPException(status_code=404, detail="Link not found")
    # Remove the inverse row too (e.g. deleting "blocks" also removes the
    # counterpart "blocked_by" row on the other task) so links never go stale
    # on one side.
    inverse_type = _INVERSE_LINK.get(link.link_type)
    if inverse_type:
        await db.execute(
            TaskLink.__table__.delete().where(
                TaskLink.task_id == link.linked_task_id,
                TaskLink.linked_task_id == task_id,
                TaskLink.link_type == inverse_type,
            )
        )
    await db.delete(link)
    await db.commit()
    return {"ok": True}

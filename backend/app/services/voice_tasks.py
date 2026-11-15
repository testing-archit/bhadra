"""Authenticated voice-to-Jira, reusing task ownership and two-way sync.

The audio fingerprint deduplicates retries per account. A dedicated connection
holds the advisory lock across the existing helpers' commits. Never retry a
Jira POST automatically: a lost response can mean the issue was created.
"""
import asyncio
import hashlib
import re
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.db import engine
from app.database.models import MeetingTask
from app.services import jira_service, live_assist


def requests_jira(command: str) -> bool:
    # Require the destination in the creation instruction, rather than a
    # product mentioned inside the task description ("review Jira permissions").
    return bool(re.search(
        r"\b(?:create|make|open|raise|file|add)\s+(?:(?:a|an|the|new)\s+)*jira\s+(?:ticket|issue|task)\b"
        r"|\b(?:create|make|open|raise|file|add)\s+(?:(?:a|an|the|new)\s+)*(?:ticket|issue|task)\s+(?:in|on|to)\s+jira\b"
        r"|\bjira\s+(?:(?:pe|par|mein|me)\s+)?(?:ticket|issue|task)\s+(?:bana do|banao|bana de|create karo|add karo)\b",
        command, re.I))


async def create(db, user, command: str, audio: bytes) -> tuple[dict, str]:
    # Release the context-read transaction before reserving a connection.
    await db.commit()
    identifier = uuid.uuid5(user.id, "voice-task:" + hashlib.sha256(audio).hexdigest())
    async with engine.connect() as connection:
        try:
            await connection.execute(text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"), {"key": str(identifier)})
            await connection.commit()
            async with AsyncSession(bind=connection, expire_on_commit=False) as task_db:
                return await _create(task_db, user, command, identifier)
        finally:
            # Session-level lock stays on this one reserved connection across
            # helper commits. Discard it if cleanup cannot be confirmed.
            try:
                await connection.rollback()
                await connection.execute(text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": str(identifier)})
                await connection.commit()
            except BaseException:
                await connection.invalidate()
                raise


async def _create(db, user, command, identifier):
    from app.routes.tasks import add_manual_task
    task = await db.get(MeetingTask, identifier)
    replay = task is not None
    if task is None:
        parsed = await asyncio.to_thread(live_assist.parse_task, command, timeout_seconds=12)
        task, _ = await add_manual_task(db, user, owner=parsed["owner"], description=parsed["description"],
            deadline=parsed["deadline"], origin="live", task_id=identifier)
    if task.deleted_at is not None:
        return {}, "That voice request was already handled and its task was deleted. Please record a new request."
    value = {"id": str(task.id), "description": task.description, "owner": task.owner, "deadline": task.deadline}
    if not requests_jira(command):
        return value, ""
    if not task.owner and task.description == command.strip()[:500]:
        return value, "Saved the request in Wilco. I couldn't reliably extract the ticket details; review the task before sending it to Jira."
    if replay and not task.jira_issue_key:
        return value, "The task is saved in Wilco. Check its Jira status in Tasks before sending it again."
    # Persist an attempt marker BEFORE the external POST. An ambiguous
    # timeout or process crash must not cause an automatic second issue.
    if not task.jira_issue_key:
        task.jira_error = "Voice Jira submission started; check Jira before retrying."
        await db.commit()
    try:
        key = await jira_service.create_issue(db, task)
        value.update(jira_issue_key=key, jira_url=jira_service.issue_url(await jira_service.get_connection(db), key))
        assigned = bool((task.jira_snapshot or {}).get("assignee"))
        owner = f" Assigned to {task.owner}." if assigned and task.owner else ""
        if task.owner and not assigned:
            owner = f" Requested owner {task.owner}; Jira assignment could not be confirmed."
        return value, f"Created Jira ticket {key}: {task.description}.{owner}"
    except jira_service.JiraError:
        await db.rollback()
        return value, "Saved the task in Wilco, but couldn't confirm a Jira ticket. Check the task in Tasks before retrying."

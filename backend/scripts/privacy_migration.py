"""Bring existing data under the privacy rules (app/services/privacy_service.py).

1. Access that came only from Jira is taken back: sending a task to Jira no
   longer opens its meeting to the whole Jira team. The rows go back to
   "waiting for access" rather than away — some were people heard in the
   call whom Jira had let in — so the organizer can let real participants
   back in with one click (People and access).
2. Tasks whose owner wasn't in the meeting were visible to them before these
   rules existed, so they've already seen them: they're marked as sent
   (the task only, not the meeting) rather than vanishing from their list.

Idempotent.

    python scripts/privacy_migration.py [--dry-run]
"""

import asyncio
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database.db import async_session
from app.database.models import Meeting, MeetingAttendee, MeetingTask, User
from app.services import privacy_service


async def main(dry_run: bool) -> None:
    async with async_session() as db:
        jira_rows = (await db.execute(
            select(MeetingAttendee, Meeting.title).join(Meeting, Meeting.id == MeetingAttendee.meeting_id)
            .where(MeetingAttendee.source == "jira", MeetingAttendee.access == "granted")
        )).all()
        for row, title in jira_rows:
            print(f"Jira access back to waiting: {row.display_name} on {title!r}")
            row.access = "pending"
        await db.flush()

        tasks = (await db.execute(
            select(MeetingTask).join(Meeting, Meeting.id == MeetingTask.meeting_id).where(
                MeetingTask.deleted_at.is_(None), Meeting.deleted_at.is_(None), MeetingTask.owner_user_id.isnot(None),
            )
        )).scalars().all()
        inside = await privacy_service.owners_in_meeting(db, tasks)
        names = {u.id: u.name or u.email for u in (await db.execute(select(User))).scalars().all()}
        now = datetime.datetime.now(datetime.UTC)
        kept = 0
        for task in tasks:
            if privacy_service.owner_access(task, inside) == "held":
                print(f"keep sent to {names.get(task.owner_user_id)}: {task.description[:70]!r}")
                task.owner_shared_at = now
                kept += 1
        print(f"{len(jira_rows)} Jira grants back to waiting, {kept} tasks kept with their owners")
        if dry_run:
            await db.rollback()
        else:
            await db.commit()


if __name__ == "__main__":
    asyncio.run(main("--dry-run" in sys.argv))

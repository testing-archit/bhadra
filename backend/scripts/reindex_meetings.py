import argparse
import asyncio
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import async_session  # noqa: E402
from app.database.models import Decision, Meeting, MeetingTask, Risk  # noqa: E402
from app.services import qdrant_service  # noqa: E402


async def reindex(meeting_id: uuid.UUID | None) -> int:
    query = select(Meeting).options(
        selectinload(Meeting.tasks).selectinload(MeetingTask.project),
        selectinload(Meeting.decisions).selectinload(Decision.project),
        selectinload(Meeting.risks).selectinload(Risk.project),
    )
    if meeting_id:
        query = query.where(Meeting.id == meeting_id)

    async with async_session() as db:
        meetings = (await db.execute(query.order_by(Meeting.date))).scalars().all()

    for meeting in meetings:
        await asyncio.to_thread(
            qdrant_service.upsert_meeting,
            str(meeting.id),
            meeting.title,
            meeting.date.isoformat(),
            meeting.summary or "",
            meeting.transcript or "",
            [
                {
                    "decision": item.decision,
                    "reason": item.reason or "",
                    "alternatives": item.alternatives or [],
                    "project": item.project.name if item.project else "",
                }
                for item in meeting.decisions
            ],
            [
                {
                    "task": item.description,
                    "assignedTo": item.owner or "",
                    "dueDate": item.deadline or "",
                    "priority": item.priority or "",
                    "project": item.project.name if item.project else "",
                }
                for item in meeting.tasks
            ],
            meeting.department,
            [
                {
                    "risk": item.description,
                    "severity": item.severity or "",
                    "project": item.project.name if item.project else "",
                }
                for item in meeting.risks
            ],
        )
        print(f"Indexed {meeting.id}: {meeting.title}")
    return len(meetings)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild meeting vectors in Qdrant")
    parser.add_argument("--meeting-id", type=uuid.UUID)
    args = parser.parse_args()
    count = asyncio.run(reindex(args.meeting_id))
    print(f"Completed: {count} meeting(s)")


if __name__ == "__main__":
    main()

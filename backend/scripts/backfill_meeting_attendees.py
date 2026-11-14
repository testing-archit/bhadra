"""Give existing meetings an attendee list.

Meeting access became attendee-based. Every pre-existing meeting still works
without this script — its recorder is allowed in via `meetings.user_id` — but
everyone *else* who was in those meetings loses them. Where we already know who
was there, this puts them back:

* `recording_sessions.attendees` — the structured list the web recorder saved.
* `recording_sessions.participants` — the older plain-name list, resolved
  against the directory the same way a live meeting's names are.

Idempotent: rows are merged, never duplicated, and an existing attendee list is
left alone. Run it after scripts/init_db.py.

    python scripts/backfill_meeting_attendees.py [--dry-run]
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.database.db import async_session
from app.database.models import Meeting, MeetingAttendee, RecordingSession
from app.services import attendee_service


async def main(dry_run: bool = False) -> None:
    async with async_session() as db:
        recordings = (
            await db.execute(
                select(RecordingSession).where(RecordingSession.meeting_id.isnot(None))
            )
        ).scalars().all()

        already = {
            meeting_id
            for (meeting_id,) in (
                await db.execute(select(MeetingAttendee.meeting_id).distinct())
            ).all()
        }

        examined = skipped = updated = 0
        for recording in recordings:
            examined += 1
            if recording.meeting_id in already:
                skipped += 1
                continue
            raw = recording.attendees or list(recording.participants or [])
            if not raw:
                skipped += 1
                continue
            meeting = await db.get(Meeting, recording.meeting_id)
            if meeting is None:
                skipped += 1
                continue

            resolved = await attendee_service.resolve(db, raw)
            names = ", ".join(
                f"{item['name']}{'' if item['kind'] == 'internal' else ' (external)'}"
                for item in resolved
            )
            print(f"{meeting.title[:50]:<52} <- {names}")
            if not dry_run:
                await attendee_service.apply_to_meeting(
                    db,
                    meeting.id,
                    resolved,
                    owner_user_id=meeting.user_id,
                    source="manual",
                )
            updated += 1

        if dry_run:
            print(f"\nDry run: {updated} meeting(s) would gain attendees "
                  f"({skipped} skipped, {examined} recordings examined).")
            return
        await db.commit()
        print(f"\nBackfilled {updated} meeting(s) ({skipped} skipped, {examined} recordings examined).")


if __name__ == "__main__":
    asyncio.run(main(dry_run="--dry-run" in sys.argv))

"""Re-name the speakers of notetaker meetings with the current caption matcher
(`speaker_mapping.name_speakers`), for meetings recorded before it improved.

Only speaker labels change — transcript text, corrections and notes are left
alone; the meeting page then shows its notes as out of date, with Regenerate. A meeting whose speakers someone already renamed by hand is skipped:
a person's choice is never overruled.

Idempotent.

    python scripts/rename_speakers_from_captions.py [--dry-run] [--days 30]
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text

from app.database.db import async_session
from app.database.models import Meeting, MeetingInsight, RecordingSession, TranscriptEdit
from app.routes.bot import _speaker_activity
from app.routes.recordings import _session_dir
from app.services import meeting_pipeline, speaker_mapping, transcript_service


async def main(dry_run: bool, days: int) -> None:
    # The notetaker's own caption name (bot/config.py BOT_DISPLAY_NAME).
    bot_names = {"Bhadra Notetaker", "Charcha Notetaker"}
    changed_meetings = []
    async with async_session() as db:
        rows = (
            await db.execute(
                select(Meeting, RecordingSession.id)
                .join(RecordingSession, RecordingSession.meeting_id == Meeting.id)
                .where(Meeting.source.in_(("bot", "capture")))
                .where(Meeting.created_at > text(f"now() - interval '{int(days)} days'"))
                .order_by(Meeting.created_at)
            )
        ).all()
        for meeting, recording_id in rows:
            directory = _session_dir(recording_id)
            captions_path, diarization_path = directory / "captions.json", directory / "recording.diarization.json"
            if not captions_path.exists() or not diarization_path.exists():
                continue
            renamed_by_hand = (
                await db.execute(
                    select(TranscriptEdit.id)
                    .where(TranscriptEdit.meeting_id == meeting.id, TranscriptEdit.field == "speaker")
                    .limit(1)
                )
            ).first()
            if renamed_by_hand:
                continue
            captions = json.loads(captions_path.read_text(encoding="utf-8"))
            turns = json.loads(diarization_path.read_text(encoding="utf-8"))["turns"]
            names = speaker_mapping.name_speakers(turns, captions, bot_names)
            segments = await transcript_service.load_segments(db, meeting.id)
            current = {s.speaker_key: s.speaker_label for s in segments if s.speaker_key.isdigit()}
            changes = {key: names.get(key) for key in current if names.get(key) != current[key]}
            if not changes:
                continue
            print(f"{meeting.created_at:%Y-%m-%d %H:%M} {meeting.title[:50]!r} {meeting.id}")
            for key, label in sorted(changes.items()):
                print(f"    {transcript_service.generic_label(key)}: {current[key] or '-'} -> {label or '-'}")
            changed_meetings.append(meeting.id)
            if dry_run:
                continue
            for segment in segments:
                if segment.speaker_key in changes:
                    segment.speaker_label = changes[segment.speaker_key]
            # Notes were written with the old names (task owners, who said
            # what): a new transcript revision makes the meeting page say so
            # and offer "Regenerate", as a rename by hand does.
            meeting.transcript_revision = (meeting.transcript_revision or 1) + 1
            meeting.transcript = transcript_service.render_transcript(segments)
            (directory / "speaker_names.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
            recording = await db.get(RecordingSession, recording_id)
            recording.participants = sorted(set(names.values())) or None
            insight = await db.get(MeetingInsight, meeting.id)
            if insight is not None:
                insight.speaker_activity = _speaker_activity(turns, names)
            await db.commit()
    if not dry_run:
        for meeting_id in changed_meetings:
            await meeting_pipeline.reindex_after_edit(meeting_id)
    print(f"{len(changed_meetings)} meeting(s) {'would be ' if dry_run else ''}re-named")


if __name__ == "__main__":
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 30
    asyncio.run(main("--dry-run" in sys.argv, days))

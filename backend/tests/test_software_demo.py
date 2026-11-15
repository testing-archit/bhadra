from sqlalchemy import select

from app.database.db import async_session
from app.database.models import Decision, EmailOutbox, Meeting, MeetingAttendee, MeetingInsight, MeetingTask, TranscriptSegment
from app.services.demo_seed import SEED_PREFIX, seed_workspace


async def test_software_workspace_has_grounded_moments_and_useful_task_states(member_user, other_member_user):
    async with async_session() as db:
        counts = await seed_workspace(db, member_user, other_member_user)
        await db.commit()
        meetings = (await db.scalars(select(Meeting).where(Meeting.user_id == member_user.id,
            Meeting.client_meeting_id.like(SEED_PREFIX + '%')))).all()
        ids = [meeting.id for meeting in meetings]
        segments = (await db.scalars(select(TranscriptSegment).where(TranscriptSegment.meeting_id.in_(ids)))).all()
        by_id = {str(segment.id): segment for segment in segments}
        tasks = (await db.scalars(select(MeetingTask).where(MeetingTask.meeting_id.in_(ids)))).all()
        decisions = (await db.scalars(select(Decision).where(Decision.meeting_id.in_(ids)))).all()
        assert counts['meetings'] >= 18 and counts['tasks'] >= 40
        assert len(segments) >= 200
        assert {task.status for task in tasks} >= {'pending', 'in_progress', 'done'}
        assert any(task.owner_user_id == member_user.id and task.status == 'pending' for task in tasks)
        assert any(task.due_date is None and not task.owner for task in tasks)
        assert any(task.verified_at for task in tasks) and any(not task.verified_at for task in tasks)
        assert any(decision.conflict_note for decision in decisions)
        for item in [*tasks, *decisions]:
            assert item.evidence
            ref = item.evidence[0]
            segment = by_id[ref['segment_id']]
            assert segment.meeting_id == item.meeting_id and ref['excerpt'] == segment.text
            assert ref['start_ms'] == segment.start_ms and ref['verified']
        for meeting in meetings:
            assert meeting.title.startswith('Demo · ') and meeting.summary.startswith('Synthetic demo.')
            own_segments = [segment for segment in segments if segment.meeting_id == meeting.id]
            assert all(0 <= segment.start_ms < segment.end_ms <= meeting.duration_minutes*60000 for segment in own_segments)
            assert all(segment.confidence is None for segment in own_segments)
            assert await db.get(MeetingInsight, meeting.id)
        confidential = [meeting.id for meeting in meetings if meeting.confidential]
        assert confidential
        assert not (await db.scalars(select(MeetingAttendee).where(MeetingAttendee.meeting_id.in_(confidential),
            MeetingAttendee.user_id == other_member_user.id))).all()
        assert not (await db.scalars(select(EmailOutbox).where(EmailOutbox.user_id == member_user.id))).all()

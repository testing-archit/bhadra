import datetime
import uuid
from types import SimpleNamespace

from app.services import privacy_service as ps
from app.services.ai_extractor import MeetingExtraction, _merge


def _task(meeting_id, owner_id, **extra):
    return SimpleNamespace(
        id=uuid.uuid4(), meeting_id=meeting_id, owner_user_id=owner_id, description="Take over the payments work",
        owner_shared_at=None, owner_kept_private_at=None, **extra,
    )


def test_owner_access_states():
    meeting, founder, avni = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    inside = {(meeting, founder)}
    assert ps.owner_access(_task(meeting, founder), inside) == "meeting"
    assert ps.owner_access(_task(meeting, avni), inside) == "held"
    assert ps.owner_access(_task(meeting, None), inside) is None
    now = datetime.datetime.now(datetime.UTC)
    assert ps.owner_access(_task(meeting, avni, ), inside) == "held"
    shared = _task(meeting, avni)
    shared.owner_shared_at = now
    assert ps.owner_access(shared, inside) == "shared"
    private = _task(meeting, avni)
    private.owner_kept_private_at = now
    assert ps.owner_access(private, inside) == "private"


class Db:
    def __init__(self):
        self.added, self.executed = [], []

    def add(self, row):
        self.added.append(row)

    async def execute(self, statement):
        self.executed.append(statement)


def test_share_and_keep_private():
    db, task = Db(), _task(uuid.uuid4(), uuid.uuid4())
    ps.share_task(db, task)
    assert task.owner_shared_at is not None
    note = db.added[0]
    # The task alone: no meeting title, link to the task not the meeting.
    assert note.link == f"/tasks?task={task.id}" and "meeting" not in note.message.lower()
    ps.keep_private(task)
    assert task.owner_shared_at is None and task.owner_kept_private_at is not None


async def test_marking_confidential_drops_the_public_link_and_jira_access():
    db = Db()
    meeting = SimpleNamespace(id=uuid.uuid4(), confidential=False, confidential_source=None, confidential_reason=None, share_token="abc")
    await ps.set_confidential(db, meeting, True, source="manual", reason="personnel decision")
    assert meeting.confidential and meeting.share_token is None and meeting.confidential_reason == "personnel decision"
    assert "meeting_attendees" in str(db.executed[0]) and "source" in str(db.executed[0])


async def test_ai_flag_marks_but_never_overrules_a_person():
    db = Db()
    flagged = {"confidential": True, "confidentialReason": "personnel decision"}
    meeting = SimpleNamespace(id=uuid.uuid4(), confidential=False, confidential_source=None, confidential_reason=None, share_token=None)
    await ps.apply_ai_flag(db, meeting, flagged)
    assert meeting.confidential and meeting.confidential_source == "ai"

    unmarked = SimpleNamespace(id=uuid.uuid4(), confidential=False, confidential_source="manual", confidential_reason=None, share_token=None)
    await ps.apply_ai_flag(db, unmarked, flagged)
    assert not unmarked.confidential


def test_any_confidential_chunk_marks_the_whole_meeting():
    merged = _merge([MeetingExtraction(), MeetingExtraction(confidential=True, confidentialReason="compensation")])
    assert merged.confidential and merged.confidentialReason == "compensation"

import json
import shutil
import uuid as uuid_mod
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.config import settings
from app.database.db import async_session
from app.database.models import Decision, Meeting, MeetingAttendee, MeetingTask, RecordingSession, Trace
from app.routes.recordings import _session_dir
from app.services import speaker_mapping
from tests.conftest import TEST_PREFIX, auth_headers

BOT_SECRET = "pytest-bot-secret"


def _turn(speaker: int, start: float, end: float, text: str = "words") -> dict:
    return {"speaker": speaker, "start": start, "end": end, "text": text}


def test_speakers_are_named_by_caption_overlap():
    turns = [_turn(0, 0, 10), _turn(1, 10, 20), _turn(0, 20, 30)]
    captions = [
        {"speaker": "Asha", "text": "hello", "start": 1, "end": 9},
        {"speaker": "Ravi", "text": "hi", "start": 11, "end": 19},
        {"speaker": "Asha", "text": "again", "start": 21, "end": 29},
    ]
    assert speaker_mapping.name_speakers(turns, captions) == {"0": "Asha", "1": "Ravi"}


def test_ambiguous_or_bot_speakers_keep_generic_labels():
    turns = [_turn(0, 0, 10)]
    split = [
        {"speaker": "Asha", "text": "a", "start": 0, "end": 5},
        {"speaker": "Ravi", "text": "b", "start": 5, "end": 10},
        {"speaker": "Kiran", "text": "c", "start": 3, "end": 7},
    ]
    assert speaker_mapping.name_speakers(turns, split) == {}
    bot_only = [{"speaker": "Bhadra Notetaker", "text": "x", "start": 0, "end": 10}]
    assert speaker_mapping.name_speakers(turns, bot_only, {"Bhadra Notetaker"}) == {}


def test_one_caption_name_never_covers_two_main_voices():
    # Only Satyendra's captions came through, but two people talked at length:
    # the second main voice stays unnamed instead of becoming Satyendra too,
    # while a short fragment of the matched voice keeps the name.
    turns = [_turn(0, 0, 50), _turn(1, 50, 100), _turn(0, 100, 150), _turn(2, 150, 165), _turn(1, 165, 200)]
    captions = [
        {"speaker": "Satyendra", "text": "a", "start": 0, "end": 150},
        {"speaker": "Satyendra", "text": "b", "start": 150, "end": 200},
    ]
    names = speaker_mapping.name_speakers(turns, captions)
    assert names == {"0": "Satyendra", "2": "Satyendra"}


def test_long_overlapping_caption_blocks_are_matched_by_their_words():
    # Production, 2026-10-09: Meet kept caption blocks open for 30-140 s and
    # Asha's and Ravi's blocks overlapped, so no voice had half its overlap
    # with one name and the whole meeting stayed "Speaker 1..5".
    turns = [
        _turn(0, 0, 8, "the family tree screen is ready on staging"),
        _turn(1, 8, 14, "upload the apk to testflight tonight please"),
        _turn(0, 14, 22, "staging build needs the family tree fixes"),
        _turn(1, 22, 30, "testflight invite goes to the whole team"),
    ]
    captions = [
        {"speaker": "Asha", "text": "the family tree screen is ready on staging. staging build needs the family tree fixes", "start": 0, "end": 60},
        {"speaker": "Ravi", "text": "upload the apk to testflight tonight please. testflight invite goes to the whole team", "start": 2, "end": 58},
    ]
    assert speaker_mapping.name_speakers(turns, captions) == {"0": "Asha", "1": "Ravi"}


def test_captions_transcript_orders_and_skips_bot():
    captions = [
        {"speaker": "Ravi", "text": "second", "start": 5, "end": 6},
        {"speaker": "Asha", "text": "first", "start": 1, "end": 2},
        {"speaker": "Bhadra Notetaker", "text": "beep", "start": 3, "end": 4},
    ]
    assert speaker_mapping.captions_transcript(captions, {"Bhadra Notetaker"}) == "Asha: first\nRavi: second"


async def test_bot_ingest_rejects_wrong_secret(client):
    with patch.object(settings, "bot_api_secret", BOT_SECRET):
        response = await client.post(
            "/api/bot/ingest", headers={"Authorization": "Bot nope"}, data={"metadata": "{}"}
        )
    assert response.status_code == 401


async def test_bot_ingest_disabled_without_secret(client):
    with patch.object(settings, "bot_api_secret", ""):
        response = await client.post(
            "/api/bot/ingest", headers={"Authorization": "Bot "}, data={"metadata": "{}"}
        )
    assert response.status_code == 503


async def test_bot_ingest_skips_meetings_with_no_internal_attendee(client, member_user):
    metadata = {
        "event_id": f"{TEST_PREFIX}evt", "event_start": "2026-10-06T10:00:00+05:30",
        "organizer_email": "client@outside.example", "attendees": [{"email": "vendor@outside.example"}],
        "captions": [{"speaker": "Client", "text": "hello", "start": 0, "end": 2}],
    }
    with patch.object(settings, "bot_api_secret", BOT_SECRET):
        response = await client.post(
            "/api/bot/ingest",
            headers={"Authorization": f"Bot {BOT_SECRET}"},
            data={"metadata": json.dumps(metadata)},
        )
    assert response.status_code == 200
    assert response.json() == {"status": "skipped", "reason": "no_internal_attendee"}


async def test_bot_ingest_files_meeting_under_organizer_with_named_transcript(
    client, member_user, other_member_user, mock_extraction, mock_qdrant_upsert
):
    detailed = {
        "transcript": "Speaker 1: we ship friday\nSpeaker 2: agreed",
        "turns": [
            {**_turn(0, 0, 8, "we ship friday"), "confidence": 0.9, "speaker_confidence": 0.9, "word_count": 3},
            {**_turn(1, 8, 12, "agreed"), "confidence": 0.9, "speaker_confidence": 0.9, "word_count": 1},
        ],
        "diagnostics": {},
    }
    metadata = {
        "event_id": f"{TEST_PREFIX}{uuid_mod.uuid4().hex}",
        "event_start": "2026-10-06T10:00:00+05:30",
        "title": f"{TEST_PREFIX}Bot standup",
        "organizer_email": member_user.email.upper(),
        "attendees": [
            {"email": other_member_user.email, "name": "Sales Person"},
            {"email": settings.notetaker_email, "name": "Notetaker"},
            {"email": "client@outside.example", "name": "Client"},
        ],
        "captions": [
            {"speaker": "Asha", "text": "we ship friday", "start": 1, "end": 7},
            {"speaker": "Ravi", "text": "agreed", "start": 9, "end": 11},
        ],
        "duration_seconds": 600,
        "bot_display_name": "Bhadra Notetaker",
    }
    with (
        patch.object(settings, "bot_api_secret", BOT_SECRET),
        patch("app.services.transcriber.transcribe_audio_detailed", new=AsyncMock(return_value=detailed)),
    ):
        response = await client.post(
            "/api/bot/ingest",
            headers={"Authorization": f"Bot {BOT_SECRET}"},
            data={"metadata": json.dumps(metadata)},
            files={"audio": ("meeting.webm", b"\x1a" * (32 * 1024), "audio/webm")},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ingested"
    mid = uuid_mod.UUID(body["meeting_id"])

    transcript_sent = mock_extraction.call_args.args[0]
    assert transcript_sent == "Asha: we ship friday\nRavi: agreed"

    async with async_session() as db:
        meeting = await db.get(Meeting, mid)
        assert meeting.user_id == member_user.id
        attendee_rows = (
            await db.execute(select(MeetingAttendee).where(MeetingAttendee.meeting_id == mid))
        ).scalars().all()
        internal = {row.user_id for row in attendee_rows if row.user_id}
        assert internal == {member_user.id, other_member_user.id}
        assert not any((row.email or "") == settings.notetaker_email for row in attendee_rows)

        recording = (
            await db.execute(select(RecordingSession).where(RecordingSession.meeting_id == mid))
        ).scalar_one()
        directory = _session_dir(recording.id)
        assert json.loads((directory / "speaker_names.json").read_text()) == {"0": "Asha", "1": "Ravi"}
        assert (directory / "recording.diarization.json").exists()

    # A retried upload must not create a second meeting.
    with (
        patch.object(settings, "bot_api_secret", BOT_SECRET),
        patch("app.services.transcriber.transcribe_audio_detailed", new=AsyncMock(return_value=detailed)),
    ):
        retry = await client.post(
            "/api/bot/ingest",
            headers={"Authorization": f"Bot {BOT_SECRET}"},
            data={"metadata": json.dumps(metadata)},
            files={"audio": ("meeting.webm", b"\x1a" * (32 * 1024), "audio/webm")},
        )
    assert retry.json()["meeting_id"] == str(mid)
    assert retry.json()["deduplicated"] is True

    shutil.rmtree(directory, ignore_errors=True)
    async with async_session() as db:
        await db.execute(RecordingSession.__table__.delete().where(RecordingSession.meeting_id == mid))
        await db.execute(MeetingAttendee.__table__.delete().where(MeetingAttendee.meeting_id == mid))
        await db.execute(Trace.__table__.delete().where(Trace.meeting_id == mid))
        await db.execute(MeetingTask.__table__.delete().where(MeetingTask.meeting_id == mid))
        await db.execute(Decision.__table__.delete().where(Decision.meeting_id == mid))
        await db.execute(Meeting.__table__.delete().where(Meeting.id == mid))
        await db.commit()


async def test_bot_ingest_keeps_audio_and_timed_captions_when_transcription_fails(
    client, member_user, mock_extraction, mock_qdrant_upsert
):
    """A Prisma failure must not lose the recording: the audio is stored for
    playback and a later retry, caption lines keep their timings for
    click-to-seek, and the transcription stage says it failed."""
    metadata = {
        "event_id": f"{TEST_PREFIX}{uuid_mod.uuid4().hex}",
        "event_start": "2026-10-06T10:00:00+05:30",
        "title": f"{TEST_PREFIX}Bot outage",
        "organizer_email": member_user.email,
        "captions": [
            {"speaker": "Asha", "text": "budget paanch lakh hai", "start": 2, "end": 6},
            {"speaker": "Bhadra Notetaker", "text": "beep", "start": 6, "end": 7},
            {"speaker": "Ravi", "text": "theek hai", "start": 8, "end": 10},
        ],
        "bot_display_name": "Bhadra Notetaker",
    }
    with (
        patch.object(settings, "bot_api_secret", BOT_SECRET),
        patch("app.services.transcriber.transcribe_audio_detailed", new=AsyncMock(side_effect=RuntimeError("Prisma error 400"))),
    ):
        response = await client.post(
            "/api/bot/ingest",
            headers={"Authorization": f"Bot {BOT_SECRET}"},
            data={"metadata": json.dumps(metadata)},
            files={"audio": ("meeting.webm", b"\x1a" * (32 * 1024), "audio/webm")},
        )
    assert response.status_code == 200, response.text
    mid = uuid_mod.UUID(response.json()["meeting_id"])
    headers = auth_headers(member_user)

    transcript = (await client.get(f"/api/meetings/{mid}/transcript", headers=headers)).json()
    assert [(s["speaker"], s["start_ms"]) for s in transcript["segments"]] == [("Asha", 2000), ("Ravi", 8000)]
    assert transcript["has_recording"] is True
    stages = {s["stage"]: s for s in (await client.get(f"/api/meetings/{mid}/processing", headers=headers)).json()["stages"]}
    assert stages["transcription"]["status"] == "failed"
    assert "captions were used" in stages["transcription"]["last_error"]

    async with async_session() as db:
        recording = (await db.execute(select(RecordingSession).where(RecordingSession.meeting_id == mid))).scalar_one()
        directory = _session_dir(recording.id)
        assert (directory / "recording.webm").stat().st_size == 32 * 1024
    shutil.rmtree(directory, ignore_errors=True)
    async with async_session() as db:
        await db.execute(RecordingSession.__table__.delete().where(RecordingSession.meeting_id == mid))
        await db.execute(MeetingAttendee.__table__.delete().where(MeetingAttendee.meeting_id == mid))
        await db.execute(Trace.__table__.delete().where(Trace.meeting_id == mid))
        await db.execute(MeetingTask.__table__.delete().where(MeetingTask.meeting_id == mid))
        await db.execute(Decision.__table__.delete().where(Decision.meeting_id == mid))
        await db.execute(Meeting.__table__.delete().where(Meeting.id == mid))
        await db.commit()


def test_presentation_captions_are_credited_to_the_presenter():
    from app.services.speaker_mapping import speaker_display_name

    assert speaker_display_name("Archit Gupta's Presentation") == "Archit Gupta"
    assert speaker_display_name("Astha Sethi’s presentation") == "Astha Sethi"
    assert speaker_display_name("Presentation (Astha Sethi)") == "Astha Sethi"
    assert speaker_display_name("Archit Gupta (Presenting)") == "Archit Gupta"
    assert speaker_display_name("  Archit Gupta ") == "Archit Gupta"
    assert speaker_display_name("Presentation Team") == "Presentation Team"
    assert speaker_display_name(None) == ""


def test_quiet_voice_takes_the_unclaimed_caption_name_not_the_loud_one():
    # Production, 2026-10-12 stand-up: Ravi's long caption blocks overlapped
    # everyone's, so Anmol's voice matched Ravi slightly better than Anmol and
    # was filed as a fragment of Ravi while "Anmol" went unused.
    turns = [
        _turn(0, 0, 60, "release plan staging build testflight review apk upload"),
        _turn(1, 60, 66, "yep sounds nice no questions going mute"),
        _turn(0, 66, 120, "release plan staging build testflight review apk upload"),
    ]
    captions = [
        {"speaker": "Ravi", "text": "release plan staging build testflight review apk upload sounds nice", "start": 0, "end": 120},
        {"speaker": "Anmol", "text": "yep sounds nice questions", "start": 60, "end": 66},
    ]
    assert speaker_mapping.name_speakers(turns, captions) == {"0": "Ravi", "1": "Anmol"}


def test_uncaptioned_voices_are_not_filed_under_the_main_speaker():
    # Production, 2026-10-13: Meet captioned Ravi 77 times but Sarthak and
    # Anmol (speaking Hindi) only 3 and 5 times, and every other voice
    # became "Ravi". A voice that barely sits under Ravi's captions isn't a
    # fragment of him: it takes a name nobody claimed when their captions
    # line up with it, else keeps its generic label.
    turns, captions = [], []
    for start in range(0, 300, 30):
        turns.append(_turn(0, start, start + 20, "release plan staging build testflight review"))
        captions.append({"speaker": "Ravi", "text": "release plan staging build testflight review", "start": start + 1, "end": start + 20})
    turns += [
        _turn(1, 20, 28, "kal ka update"),     # Sarthak, captioned once
        _turn(2, 50, 58, "abhi dekhta hoon"),  # Anmol, captioned once
        _turn(3, 80, 88, "theek hai sir"),     # never captioned
        _turn(1, 110, 118, "haan"),
        _turn(2, 140, 148, "ok"),
        _turn(3, 170, 178, "ji"),
    ]
    captions += [
        {"speaker": "Sarthak", "text": "Update.", "start": 22, "end": 27},
        {"speaker": "Anmol", "text": "Okay.", "start": 52, "end": 57},
        {"speaker": "Ravi", "text": "release", "start": 85, "end": 87},
    ]
    assert speaker_mapping.name_speakers(turns, captions) == {"0": "Ravi", "1": "Sarthak", "2": "Anmol"}

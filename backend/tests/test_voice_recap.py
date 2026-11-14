import base64
from unittest.mock import patch

from sqlalchemy import select

from app.config import settings
from app.database.db import async_session
from app.database.models import Meeting, MeetingTask
from tests.conftest import auth_headers

REPLY = '''{"title": "Ramesh supplier payment", "summary": "Sharma ji ko Ramesh ko 1,240 rupaye Friday tak dene hain.",
"action_items": [{"owner": "Sharma ji", "task": "Ramesh ko 1,240 rupaye dena", "due": "Friday"}],
"amounts": ["1,240 rupaye - Ramesh supplier"], "spoken_recap": "Sharma ji, Ramesh ko Friday tak 1,240 rupaye dene hain."}'''


async def test_voice_note_recap_saves_a_meeting_with_tasks(client, member_user):
    heard = {"turns": [{"text": "Sharma ji, Ramesh ko Friday tak 1,240 rupaye dena hai."}], "language": "hi-IN", "metadata": {"duration": 42}}
    with patch.object(settings, "gnani_api_key", "t"), patch.object(settings, "gemini_api_key", "t"), patch(
        "app.services.transcriber.transcribe_audio_detailed", return_value=heard
    ), patch("app.services.gemini_service.generate_text", return_value=(REPLY, {})), patch(
        "app.services.tts_service.synthesize", return_value=b"ID3recap"
    ):
        response = await client.post(
            "/api/recap", files={"audio": ("note.opus", b"x", "audio/ogg")}, data={"kind": "voice_note"}, headers=auth_headers(member_user)
        )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Ramesh supplier payment" and body["language"] == "hi-IN"
    assert body["action_items"] == [{"owner": "Sharma ji", "task": "Ramesh ko 1,240 rupaye dena", "due": "Friday"}]
    assert base64.b64decode(body["audio"]) == b"ID3recap"
    async with async_session() as db:
        meeting = await db.get(Meeting, __import__("uuid").UUID(body["meeting_id"]))
        assert meeting.source == "voice_note" and "1,240 rupaye - Ramesh supplier" in meeting.summary
        tasks = (await db.scalars(select(MeetingTask).where(MeetingTask.meeting_id == meeting.id))).all()
        assert [(t.owner, t.deadline) for t in tasks] == [("Sharma ji", "Friday")]
        for task in tasks:
            await db.delete(task)
        await db.delete(meeting)
        await db.commit()


async def test_recap_without_speech_says_so(client, member_user):
    with patch.object(settings, "gnani_api_key", "t"), patch.object(settings, "gemini_api_key", "t"), patch(
        "app.services.transcriber.transcribe_audio_detailed", return_value={"turns": []}
    ):
        response = await client.post("/api/recap", files={"audio": ("a.mp3", b"x", "audio/mpeg")}, headers=auth_headers(member_user))
    assert response.status_code == 422
    assert "No speech" in response.json()["detail"]

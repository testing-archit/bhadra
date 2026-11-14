from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_recording_lifecycle(client, member_user, make_meeting, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "recordings_dir", str(tmp_path))
    headers = auth_headers(member_user)

    created = await client.post(
        "/api/recordings",
        headers=headers,
        json={
            "title": "",
            "meeting_type": "physical",
            "language": "hinglish",
            # Names are no longer filtered against a hardcoded roster: anyone
            # can be in the room. A name that matches a Charcha account becomes
            # an internal attendee (and gains access to the meeting); anyone
            # else is kept as an external attendee with no access.
            "participants": ["Zeta Testperson", "Yara Testperson", "zeta testperson"],
        },
    )
    assert created.status_code == 200
    recording = created.json()
    assert recording["status"] == "recording"
    assert recording["title"] == "Meeting in progress"
    assert recording["participants"] == ["Zeta Testperson", "Yara Testperson"]
    assert [item["kind"] for item in recording["attendees"]] == ["external", "external"]

    active = await client.get("/api/recordings/active", headers=headers)
    assert active.status_code == 200
    assert recording["id"] in [item["id"] for item in active.json()]

    detailed = {
        "transcript": "Speaker 1: We approved the launch plan.\nSpeaker 2: I will share it today.",
        "turns": [
            {"speaker": 0, "start": 0.0, "end": 2.0, "text": "We approved the launch plan.", "confidence": 0.95, "speaker_confidence": 0.9, "word_count": 5},
            {"speaker": 1, "start": 2.1, "end": 3.5, "text": "I will share it today.", "confidence": 0.94, "speaker_confidence": 0.88, "word_count": 5},
        ],
        "diagnostics": {"quality": "good", "detected_speakers": 2, "expected_speakers": 2, "average_speaker_confidence": 0.89, "low_confidence_share": 0.0, "turn_count": 2},
        "metadata": {"request_id": "test", "duration": 2.0, "diarizer": "v2"},
    }
    with patch(
        "app.routes.recordings.transcriber.transcribe_audio_detailed",
        new=AsyncMock(return_value=detailed),
    ):
        uploaded = await client.post(
            f"/api/recordings/{recording['id']}/chunks",
            headers=headers,
            data={"chunk_index": "0"},
            files={"chunk": ("000000.webm", b"test-webm-audio", "audio/webm")},
        )
        finalized = await client.post(
            f"/api/recordings/{recording['id']}/finalize",
            headers=headers,
            json={"duration_seconds": 243},
        )
    assert uploaded.status_code == 200
    assert uploaded.json()["transcript"].startswith("Speaker 1")
    assert finalized.status_code == 200
    assert finalized.json()["recording"]["status"] == "recorded"
    assert "launch plan" in finalized.json()["transcript"]

    diarization = await client.get(
        f"/api/recordings/{recording['id']}/diarization", headers=headers
    )
    assert diarization.status_code == 200
    assert diarization.json()["diagnostics"]["quality"] == "good"

    renamed = await client.patch(
        f"/api/recordings/{recording['id']}/speakers",
        headers=headers,
        json={"names": {"0": "Archit", "1": "Avni"}},
    )
    assert renamed.status_code == 200
    assert renamed.json()["turns"][0]["speaker_name"] == "Archit"

    corrected = await client.patch(
        f"/api/recordings/{recording['id']}/speaker-corrections",
        headers=headers,
        json={"corrections": {"0": 1}},
    )
    assert corrected.status_code == 200
    assert corrected.json()["speaker_corrections"] == {"0": 1}
    assert corrected.json()["turns"][0]["speaker_name"] == "Avni"

    audio = await client.get(f"/api/recordings/{recording['id']}/audio", headers=headers)
    assert audio.status_code == 200
    assert audio.content == b"test-webm-audio"

    meeting = await make_meeting(member_user, "linked recording", "Engineering")
    linked = await client.post(
        f"/api/recordings/{recording['id']}/link",
        headers=headers,
        json={"meeting_id": str(meeting.id)},
    )
    assert linked.status_code == 200

    named_summary = "Archit approved the launch plan and Avni committed to share it."
    with (
        patch(
            "app.routes.recordings.ai_extractor.generate_detailed_summary",
            return_value=(named_summary, {"input_tokens": 10, "output_tokens": 10}),
        ) as regenerate,
        patch("app.routes.recordings.rebuild_meeting_index") as reindex,
    ):
        renamed_linked = await client.patch(
            f"/api/recordings/{recording['id']}/speakers",
            headers=headers,
            json={"names": {"0": "Archit", "1": "Avni"}},
        )
    assert renamed_linked.status_code == 200
    regenerate.assert_called_once()
    reindex.assert_called_once()

    detail = await client.get(f"/api/meetings/{meeting.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["recording"]["id"] == recording["id"]
    assert detail.json()["recording"]["meeting_type"] == "physical"
    assert detail.json()["summary"] == named_summary
    assert "Speaker 1" not in detail.json()["summary"]


@pytest.mark.asyncio
async def test_recording_rejects_invalid_setup(client, member_user):
    response = await client.post(
        "/api/recordings",
        headers=auth_headers(member_user),
        json={"title": "", "meeting_type": "phone", "language": "unknown"},
    )
    assert response.status_code == 400

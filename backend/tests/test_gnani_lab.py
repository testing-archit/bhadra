"""Built on Gnani: each model can be tried live, voice cloning needs consent
and stays with its owner, and Evon answers Live when it's configured."""
import base64
import datetime
from unittest.mock import AsyncMock, patch

from app.config import settings
from app.services import voice_clone_service
from tests.conftest import auth_headers

EMBEDDING = {"embedding": "abc123", "shape": [1, 768], "dtype": "torch.bfloat16"}


async def test_models_reports_every_gnani_model(client, member_user):
    response = await client.get("/api/gnani/models", headers=auth_headers(member_user))
    body = response.json()
    assert response.status_code == 200
    assert set(body) == {"prisma", "timbre", "voice_clone", "evon", "warp"}
    assert body["prisma"]["model"] == settings.gnani_stt_model
    assert body["timbre"]["multilingual_model"] == settings.gnani_tts_multilingual_model


async def test_prisma_try_returns_text_language_and_latency(client, member_user):
    heard = {"turns": [{"text": "kal tak bhej dunga", "speaker": 0}], "language": "hi-IN"}
    with patch("app.services.transcriber.transcribe_audio_detailed", new=AsyncMock(return_value=heard)):
        response = await client.post("/api/gnani/prisma", headers=auth_headers(member_user),
                                     files={"audio": ("clip.webm", b"x" * 100, "audio/webm")})
    body = response.json()
    assert body["text"] == "kal tak bhej dunga" and body["language"] == "hi-IN" and body["latency_ms"] >= 0


async def test_timbre_try_names_the_model_and_voice(client, member_user):
    with patch("app.services.tts_service.synthesize", new=AsyncMock(return_value=b"ID3")):
        response = await client.post("/api/gnani/timbre", headers=auth_headers(member_user),
                                     json={"text": "வணக்கம்", "language": "ta-IN"})
    body = response.json()
    assert base64.b64decode(body["audio"]) == b"ID3"
    assert body["model"] == settings.gnani_tts_multilingual_model


async def test_voice_clone_needs_consent_and_is_only_the_owners(client, member_user, other_member_user):
    sample = {"audio": ("me.webm", b"x" * 100, "audio/webm")}
    refused = await client.post("/api/gnani/voice-clone", headers=auth_headers(member_user), files=sample, data={"consent": "false"})
    assert refused.status_code == 422
    with patch.object(voice_clone_service, "create_embedding", new=AsyncMock(return_value=EMBEDDING)):
        saved = await client.post("/api/gnani/voice-clone", headers=auth_headers(member_user), files=sample, data={"consent": "true"})
    assert saved.status_code == 200
    with patch.object(voice_clone_service, "speak", new=AsyncMock(return_value=b"ID3me")) as speak:
        mine = await client.post("/api/gnani/voice-clone/speak", headers=auth_headers(member_user), json={"text": "hello team"})
        theirs = await client.post("/api/gnani/voice-clone/speak", headers=auth_headers(other_member_user), json={"text": "hello team"})
    assert base64.b64decode(mine.json()["audio"]) == b"ID3me"
    assert voice_clone_service.secret_box.decrypt(speak.call_args.args[1].embedding_encrypted) == "abc123"
    assert theirs.status_code == 404  # nobody can speak with someone else's voice
    gone = await client.delete("/api/gnani/voice-clone", headers=auth_headers(member_user))
    assert gone.json() == {"enrolled": False}


async def test_voice_update_needs_a_voice_and_a_meeting_link(client, member_user):
    body = {"meeting_url": "https://meet.google.com/abc-defg-hij", "text": "Payments shipped; blocked on KYC keys."}
    no_voice = await client.post("/api/gnani/voice-updates", headers=auth_headers(member_user), json=body)
    assert no_voice.status_code == 409
    with patch.object(voice_clone_service, "create_embedding", new=AsyncMock(return_value=EMBEDDING)):
        await client.post("/api/gnani/voice-clone", headers=auth_headers(member_user),
                          files={"audio": ("me.webm", b"x" * 100, "audio/webm")}, data={"consent": "true"})
    bad = await client.post("/api/gnani/voice-updates", headers=auth_headers(member_user), json={**body, "meeting_url": "https://zoom.us/j/1"})
    assert bad.status_code == 422
    made = await client.post("/api/gnani/voice-updates", headers=auth_headers(member_user), json=body)
    assert made.status_code == 200 and made.json()["meeting_url"] == "https://meet.google.com/abc-defg-hij"
    listed = await client.get("/api/gnani/voice-updates", headers=auth_headers(member_user))
    assert [row["text"] for row in listed.json()][0] == body["text"]
    await client.delete("/api/gnani/voice-clone", headers=auth_headers(member_user))


async def test_live_answers_with_evon_when_configured_and_falls_back_to_gemini(client, member_user):
    heard = {"turns": [{"text": "kya decide hua?"}], "language": "hi-IN"}
    common = [patch.object(settings, "gnani_api_key", "test"),
              patch("app.services.transcriber.transcribe_audio_detailed", return_value=heard),
              patch("app.services.tts_service.synthesize", new=AsyncMock(return_value=b"ID3"))]
    for item in common:
        item.start()
    try:
        with patch.object(settings, "evon_url", "http://evon.local"), \
             patch("app.services.evon_service.chat", new=AsyncMock(return_value="Pricing same rahegi.")), \
             patch("app.services.gemini_service.generate_text") as gemini:
            evon = await client.post("/api/live/turn", files={"audio": ("t.webm", b"x", "audio/webm")}, headers=auth_headers(member_user))
        assert evon.json()["reply"] == "Pricing same rahegi." and evon.json()["reply_model"] == settings.evon_model
        gemini.assert_not_called()
        with patch.object(settings, "evon_url", "http://evon.local"), \
             patch("app.services.evon_service.chat", new=AsyncMock(side_effect=RuntimeError("down"))), \
             patch("app.services.gemini_service.generate_text", return_value=("Gemini says hi.", {})):
            fallback = await client.post("/api/live/turn", files={"audio": ("t.webm", b"x", "audio/webm")}, headers=auth_headers(member_user))
        assert fallback.json()["reply"] == "Gemini says hi." and fallback.json()["reply_model"] == settings.gemini_fast_model
    finally:
        for item in common:
            item.stop()


async def test_bot_gets_only_this_calls_voice_updates_in_the_authors_voice(client, member_user):
    import uuid
    from app.database.db import async_session
    from app.database.models import CaptureRequest
    with patch.object(voice_clone_service, "create_embedding", new=AsyncMock(return_value=EMBEDDING)):
        await client.post("/api/gnani/voice-clone", headers=auth_headers(member_user),
                          files={"audio": ("me.webm", b"x" * 100, "audio/webm")}, data={"consent": "true"})
    mine = await client.post("/api/gnani/voice-updates", headers=auth_headers(member_user),
                             json={"meeting_url": "https://meet.google.com/vcu-abcd-efg", "text": "Shipped payments."})
    await client.post("/api/gnani/voice-updates", headers=auth_headers(member_user),
                      json={"meeting_url": "https://meet.google.com/oth-abcd-efg", "text": "Other call."})
    async with async_session() as db:
        capture = CaptureRequest(id=uuid.uuid4(), user_id=member_user.id, meeting_url="https://meet.google.com/vcu-abcd-efg",
                                 meeting_code="vcu-abcd-efg", platform="google_meet", status="capturing",
                                 consent_acknowledged_at=datetime.datetime.now(datetime.UTC))
        db.add(capture)
        await db.commit()
    with patch.object(settings, "bot_api_secret", "test-bot-secret"):
        headers = {"Authorization": "Bot test-bot-secret"}
        listed = await client.get(f"/api/bot/capture-requests/{capture.id}/voice-updates", headers=headers)
        assert [row["text"] for row in listed.json()] == ["Shipped payments."]
        update_id = listed.json()[0]["id"]
        with patch.object(voice_clone_service, "speak", new=AsyncMock(return_value=b"ID3clone")):
            audio = await client.post(f"/api/bot/capture-requests/{capture.id}/voice-updates/{update_id}/audio", headers=headers)
        assert audio.content == b"ID3clone"
        await client.post(f"/api/bot/capture-requests/{capture.id}/voice-updates/{update_id}/delivered", headers=headers)
        again = await client.get(f"/api/bot/capture-requests/{capture.id}/voice-updates", headers=headers)
        assert again.json() == []
    assert mine.status_code == 200
    async with async_session() as db:
        await db.delete(await db.get(CaptureRequest, capture.id))
        await db.commit()
    await client.delete("/api/gnani/voice-clone", headers=auth_headers(member_user))

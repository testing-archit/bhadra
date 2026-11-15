"""Voice khata: spoken ledger lines become entries, balances add up per
customer however the name is said, and reminders are polite and localised."""
from unittest.mock import AsyncMock, patch

from app.services import khata_service
from app.services.khata_service import ParsedEntry
from tests.conftest import auth_headers


async def test_typed_and_spoken_notes_become_a_ledger(client, member_user):
    headers = auth_headers(member_user)
    with patch.object(khata_service, "parse", return_value=[ParsedEntry(customer="Gupta ji", kind="credit", amount=500, note="atta, dal")]):
        first = await client.post("/api/khata/text", headers=headers, json={"text": "Gupta ji ne 500 ka atta dal udhaar liya"})
    assert first.status_code == 200 and first.json()["outstanding"] == 500
    heard = {"turns": [{"text": "gupta ne 200 jama kiye"}], "language": "hi-IN"}
    with patch("app.services.transcriber.transcribe_audio_detailed", new=AsyncMock(return_value=heard)), \
         patch.object(khata_service, "parse", return_value=[ParsedEntry(customer="Gupta", kind="payment", amount=200)]):
        spoken = await client.post("/api/khata/voice", headers=headers, files={"audio": ("n.webm", b"x" * 50, "audio/webm")})
    body = spoken.json()
    assert body["heard"] == "gupta ne 200 jama kiye"
    assert [(c["customer"], c["balance"]) for c in body["customers"]] == [("Gupta", 300.0)]
    with patch.object(khata_service, "parse", return_value=[]):
        empty = await client.post("/api/khata/text", headers=headers, json={"text": "kal dukaan band rahegi"})
    assert empty.status_code == 422
    with patch.object(khata_service, "reminder", return_value="Namaste Gupta ji, Rs 300 baaki hai. 🙏") as remind, \
         patch("app.services.tts_service.synthesize", new=AsyncMock(return_value=b"ID3")):
        note = await client.post("/api/khata/reminder", headers=headers, json={"customer": "gupta JI", "language": "hi-en", "speak": True})
    assert note.json()["balance"] == 300 and note.json()["audio"]
    assert remind.call_args.args[1] == 300
    for entry in body["entries"]:
        await client.delete(f"/api/khata/entries/{entry['id']}", headers=headers)


def test_customer_key_ignores_how_the_name_is_said():
    assert khata_service.customer_key("Gupta ji") == khata_service.customer_key("gupta") == "gupta"
    assert khata_service.customer_key("Meena Didi") == "meena"

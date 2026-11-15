"""No-sign-up demo: a private seeded workspace that can't reach anything
outside itself (notetaker, calendars, voice cloning) and gets no email."""
from sqlalchemy import select

from app.database.db import async_session
from app.database.models import EmailOutbox, Meeting, User


async def test_demo_gets_a_private_seeded_workspace_and_is_fenced(client):
    response = await client.post("/api/auth/demo")
    assert response.status_code == 200
    headers = {"Authorization": f"Bearer {response.json()['token']}"}
    meetings = await client.get("/api/meetings", headers=headers)
    assert meetings.status_code == 200
    body = meetings.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    assert len(items) >= 10
    blocked = await client.post("/api/capture/requests", headers=headers,
                                json={"meeting_url": "https://meet.google.com/abc-defg-hij", "consent_acknowledged": True})
    assert blocked.status_code == 403
    assert (await client.post("/api/calendar/connect", headers=headers)).status_code == 403
    models = await client.get("/api/gnani/models", headers=headers)
    assert models.json()["demo"] is True

    other = await client.post("/api/auth/demo")
    other_headers = {"Authorization": f"Bearer {other.json()['token']}"}
    async with async_session() as db:
        first = await db.scalar(select(User).where(User.email == response.json()["email"]))
        mine = (await db.scalars(select(Meeting.id).where(Meeting.user_id == first.id))).all()
        queued = (await db.scalars(select(EmailOutbox).where(EmailOutbox.user_id == first.id))).all()
    assert queued == []
    # Another guest can't open this guest's meetings.
    assert (await client.get(f"/api/meetings/{mine[0]}", headers=other_headers)).status_code in (403, 404)
    async with async_session() as db:
        for email in (response.json()["email"], other.json()["email"]):
            await db.delete(await db.scalar(select(User).where(User.email == email)))
        await db.commit()

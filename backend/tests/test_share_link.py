from app.database.db import async_session
from app.database.models import Meeting, MeetingInsight
from tests.conftest import auth_headers


async def test_share_link_does_not_exist_until_created(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Shareable Meeting", "Engineering")

    async with async_session() as db:
        stored = await db.get(Meeting, meeting.id)
        assert stored.share_token is None

    public = await client.get("/api/meetings/shared/whatever-a-guess-would-be")
    assert public.status_code == 404


async def test_create_share_link_is_idempotent_and_public_readable(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Shareable Meeting", "Engineering")

    first = await client.post(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(member_user))
    assert first.status_code == 200
    token = first.json()["share_token"]
    assert token

    second = await client.post(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(member_user))
    assert second.status_code == 200
    assert second.json()["share_token"] == token

    public = await client.get(f"/api/meetings/shared/{token}")
    assert public.status_code == 200
    body = public.json()
    assert body["title"] == meeting.title
    assert "transcript" not in body
    assert "attendees" not in body


async def test_share_link_404_for_non_attendee(client, member_user, other_member_user, make_meeting):
    meeting = await make_meeting(other_member_user, "Sales Only Meeting", "Sales")

    response = await client.post(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(member_user))
    assert response.status_code == 404


async def test_revoke_share_link_invalidates_public_access(client, member_user, make_meeting):
    meeting = await make_meeting(member_user, "Revocable Meeting", "Engineering")

    created = await client.post(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(member_user))
    token = created.json()["share_token"]

    revoked = await client.delete(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(member_user))
    assert revoked.status_code == 200

    public = await client.get(f"/api/meetings/shared/{token}")
    assert public.status_code == 404


async def test_shared_endpoint_404_for_unknown_token(client):
    response = await client.get("/api/meetings/shared/not-a-real-token")
    assert response.status_code == 404


async def test_only_people_who_decide_access_can_make_a_public_link(client, member_user, other_member_user, make_meeting):
    from app.database.db import async_session
    from app.database.models import Meeting, MeetingAttendee

    meeting = await make_meeting(member_user, "Attendee Share Meeting", "Engineering")
    async with async_session() as db:
        db.add(MeetingAttendee(meeting_id=meeting.id, user_id=other_member_user.id, display_name="Other", access="granted"))
        await db.commit()
    # An attendee can read the meeting but can't publish it to the internet.
    refused = await client.post(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(other_member_user))
    assert refused.status_code == 403
    assert (await client.delete(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(other_member_user))).status_code == 403
    assert (await client.post(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(member_user))).status_code == 200


async def test_shared_page_carries_the_notes_but_no_quotes(client, member_user, make_meeting):
    """A stand-up's notes live in meeting_insights, not meetings.summary — the
    public page must show them, without the transcript quotes behind them."""
    meeting = await make_meeting(member_user, "Daily Stand-up", "Engineering")
    quote = {"segment_id": "s1", "quote": "a verbatim transcript line"}
    async with async_session() as db:
        db.add(MeetingInsight(
            meeting_id=meeting.id, overview="The team agreed on the APK fixes.", key_topics=["APK"], highlights=[],
            next_steps=["Ship the build"], open_questions=[],
            sections=[{"title": "APK bugs", "summary": "Basic bugs before QA.", "evidence": [quote]}],
            template_sections=[{"heading": "Blockers", "items": [{"text": "Waiting on the API", "person": "Anushka", "evidence": [quote]}]},
                               {"heading": "Updates", "items": []}],
        ))
        await db.commit()
    token = (await client.post(f"/api/meetings/{meeting.id}/share-link", headers=auth_headers(member_user))).json()["share_token"]
    response = await client.get(f"/api/meetings/shared/{token}")
    body = response.json()
    assert body["summary"] == "The team agreed on the APK fixes."
    assert body["template_sections"] == [{"heading": "Blockers", "items": [{"text": "Waiting on the API", "person": "Anushka"}]}]
    assert body["sections"] == [{"title": "APK bugs", "summary": "Basic bugs before QA."}]
    assert body["next_steps"] == ["Ship the build"] and body["key_topics"] == ["APK"]
    assert "verbatim" not in response.text

from unittest.mock import patch

from mcp.server.auth.provider import AccessToken

from app import mcp_server
from tests.conftest import auth_headers


def _as(user):
    token = AccessToken(token="t", client_id="charcha-connector", scopes=["charcha"], subject=str(user.id))
    return patch("app.mcp_server.get_access_token", return_value=token)


async def test_connector_token_works_only_on_the_mcp_endpoint(client, member_user):
    response = await client.post("/api/auth/connector-token", headers=auth_headers(member_user))
    assert response.status_code == 200
    body = response.json()
    assert body["url"].endswith("/api/mcp")
    # The regular API refuses it...
    refused = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert refused.status_code == 401
    # ...and the connector accepts it, as this person.
    access = await mcp_server.ConnectorTokenVerifier().verify_token(body["token"])
    assert access is not None and access.subject == str(member_user.id)
    # A normal session token is not a connector token.
    session = auth_headers(member_user)["Authorization"].removeprefix("Bearer ")
    assert await mcp_server.ConnectorTokenVerifier().verify_token(session) is None


async def test_tools_only_see_meetings_the_person_can_read(member_user, other_member_user, make_meeting):
    mine = await make_meeting(member_user, "Kirana pilot review", None)
    await make_meeting(other_member_user, "Someone else's salary talk", None)
    with _as(member_user):
        found = await mcp_server.search_meetings()
        titles = [m["title"] for m in found]
        assert any("Kirana pilot review" in t for t in titles)
        assert not any("salary" in t for t in titles)
        detail = await mcp_server.get_meeting(str(mine.id))
        assert "Kirana pilot review" in detail["title"]
    others = await make_meeting(other_member_user, "Private one", None)
    with _as(member_user):
        assert await mcp_server.get_meeting(str(others.id)) == {"error": "Meeting not found"}


async def test_create_task_adds_to_the_persons_list(member_user):
    with _as(member_user):
        created = await mcp_server.create_task("Send the invoice to Sharma ji", owner="Vedant", deadline="Friday")
        assert created["task"] == "Send the invoice to Sharma ji"
        assert created["owner"] == "Vedant"

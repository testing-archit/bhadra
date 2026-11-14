"""Google sign-in: only a verified Google email can claim or create an account."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import settings
from app.database.db import async_session
from app.database.models import User
from app.routes import auth


def _google(info: dict):
    response = MagicMock(is_success=True)
    response.json.return_value = info
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.get = AsyncMock(return_value=response)
    return patch("app.routes.auth.httpx.AsyncClient", return_value=client)


async def test_unverified_google_email_cannot_claim_an_existing_account(client, member_user):
    info = {"sub": f"pytest-{uuid.uuid4()}", "email": member_user.email.upper(), "email_verified": False}
    with _google(info):
        response = await client.post("/api/auth/google", json={"google_access_token": "t"})
    assert response.status_code == 403
    async with async_session() as db:
        assert (await db.get(User, member_user.id)).google_sub != info["sub"]


async def test_verified_google_email_links_case_insensitively(client, member_user):
    info = {"sub": f"pytest-{uuid.uuid4()}", "email": member_user.email.upper(), "email_verified": True}
    with _google(info):
        response = await client.post("/api/auth/google", json={"google_access_token": "t"})
    assert response.status_code == 200
    assert response.json()["email"] == member_user.email


async def test_signup_domains_limit_new_accounts_only(client, member_user):
    with patch.object(settings, "allowed_signup_domains", "bhadra.example"):
        refused = await client.post("/api/auth/register", json={"email": f"pytest_{uuid.uuid4().hex[:6]}@elsewhere.example", "password": "long enough pw"})
        assert refused.status_code == 403
        assert auth._signup_allowed("someone@BHADRA.example")

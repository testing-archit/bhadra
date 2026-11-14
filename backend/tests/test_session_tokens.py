"""Only session tokens sign in. Other tokens share JWT_SECRET (unsubscribe
links, calendar OAuth state) and must be refused before any database read."""

import uuid

import pytest
from fastapi import HTTPException

from app.dependencies import create_access_token, get_current_user
from app.services import calendar_service, email_service, jira_service


@pytest.mark.parametrize(
    "make_token",
    [
        lambda uid: email_service.unsubscribe_token(uid, "tasks"),
        lambda uid: calendar_service.make_state(uid),
        lambda uid: jira_service.make_state(uid),
    ],
    ids=["unsubscribe", "calendar-state", "jira-state"],
)
async def test_purpose_tokens_are_not_sessions(make_token):
    with pytest.raises(HTTPException) as error:
        await get_current_user(authorization=f"Bearer {make_token(uuid.uuid4())}", db=None)
    assert error.value.status_code == 401


async def test_malformed_subject_is_a_401_not_a_500():
    import jwt

    from app.config import settings

    token = jwt.encode({"sub": "not-a-uuid", "exp": 4102444800}, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(HTTPException) as error:
        await get_current_user(authorization=f"Bearer {token}", db=None)
    assert error.value.status_code == 401


def test_session_tokens_still_carry_what_get_current_user_requires():
    import jwt

    from app.config import settings

    payload = jwt.decode(create_access_token(uuid.uuid4(), "a@b.c"), settings.jwt_secret, algorithms=["HS256"])
    assert {"sub", "exp", "iat"} <= payload.keys() and "purpose" not in payload

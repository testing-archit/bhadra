"""Rate limits are per person (signed in) or per real client IP — not one
bucket for everyone behind nginx."""

import uuid

from starlette.requests import Request

from app.rate_limit import rate_limit_key
from tests.conftest import auth_headers


def _request(headers: dict) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw, "client": ("172.18.0.5", 1234), "method": "GET", "path": "/"})


def test_keys(member_user, other_member_user):
    assert rate_limit_key(_request(auth_headers(member_user))) == f"user:{member_user.id}"
    assert rate_limit_key(_request(auth_headers(member_user))) != rate_limit_key(_request(auth_headers(other_member_user)))
    # Anonymous: the browser's IP from nginx, never nginx's own address.
    assert rate_limit_key(_request({"X-Real-IP": "203.0.113.7"})) == "ip:203.0.113.7"
    assert rate_limit_key(_request({"X-Forwarded-For": "198.51.100.2, 172.18.0.5"})) == "ip:198.51.100.2"
    assert rate_limit_key(_request({})) == "ip:172.18.0.5"
    # A forged token doesn't get its own bucket.
    assert rate_limit_key(_request({"Authorization": "Bearer forged", "X-Real-IP": "203.0.113.7"})) == "ip:203.0.113.7"


async def test_one_ip_hitting_the_limit_doesnt_block_another(client):
    first = f"203.0.113.{uuid.uuid4().int % 200 + 1}"
    second = f"198.51.100.{uuid.uuid4().int % 200 + 1}"
    body = {"email": f"nobody-{uuid.uuid4().hex[:6]}@example.com"}
    codes = [(await client.post("/api/auth/password/forgot", json=body, headers={"X-Real-IP": first})).status_code for _ in range(6)]
    assert codes[:5] == [200] * 5 and codes[5] == 429
    assert (await client.post("/api/auth/password/forgot", json=body, headers={"X-Real-IP": second})).status_code == 200

"""Rate limiting keyed on who is asking.

Every request reaches the API through nginx, so the TCP peer is always
nginx: keying on it put the whole company in one bucket (20 memory-chat
questions a minute between everyone). Signed-in requests are now limited
per person; anonymous ones (sign-in, password reset) per real client IP,
taken from the X-Real-IP header nginx sets. The API port isn't published,
so only nginx can set that header.
"""

import jwt
from slowapi import Limiter
from starlette.requests import Request

from app.config import settings


def client_ip(request: Request) -> str:
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(auth.removeprefix("Bearer "), settings.jwt_secret, algorithms=["HS256"])
            if payload.get("sub"):
                return f"user:{payload['sub']}"
        except jwt.PyJWTError:
            pass  # an invalid token is limited like an anonymous caller
    return f"ip:{client_ip(request)}"


limiter = Limiter(key_func=rate_limit_key)

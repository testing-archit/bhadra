"""Symmetric encryption for secrets stored in the database (Google refresh
tokens). The key is derived from JWT_SECRET, which production already keeps
secret, so no new key has to be provisioned — rotating JWT_SECRET means
people re-link their calendars, which is the safe failure."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"charcha:secret-box:{settings.jwt_secret}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str | None:
    """None when the value can't be decrypted (e.g. JWT_SECRET changed)."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, ValueError):
        return None

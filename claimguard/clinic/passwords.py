"""Local clinic credential hashing for the synthetic platform deployment."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

_N = 1 << 14
_R = 8
_P = 1
_SALT_BYTES = 16
_KEY_BYTES = 32


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must not be blank")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_BYTES)
    return f"scrypt-v1:{base64.b64encode(salt).decode()}:{base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt_part, digest_part = encoded.split(":")
        if scheme != "scrypt-v1":
            return False
        salt = base64.b64decode(salt_part, validate=True)
        expected = base64.b64decode(digest_part, validate=True)
        if len(salt) != _SALT_BYTES or len(expected) != _KEY_BYTES:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_KEY_BYTES
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, UnicodeError, binascii.Error):
        return False

"""Short-lived signed clinic sessions with live membership lookup.

The token contains only opaque user and clinic identifiers. It never carries a
role: role changes and revoked memberships take effect on the next request.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import cast

from claimguard.clinic.access import Principal, Role


class AuthenticationError(ValueError):
    """The session or its current clinic membership is invalid."""


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class SessionSigner:
    """Sign and verify opaque session claims using an operator-managed secret."""

    def __init__(self, key: bytes) -> None:
        if len(key) < 32:
            raise ValueError("session signing key must contain at least 32 bytes")
        self._key = key

    def issue(
        self,
        user_id: str,
        tenant_id: str,
        *,
        now: datetime | None = None,
        lifetime: timedelta = timedelta(hours=8),
    ) -> str:
        if not user_id.strip() or not tenant_id.strip():
            raise ValueError("user_id and tenant_id must not be blank")
        if lifetime <= timedelta(0):
            raise ValueError("session lifetime must be positive")
        issued = now if now is not None else datetime.now(UTC)
        if issued.tzinfo is None:
            raise ValueError("session clock must be timezone-aware")
        payload = json.dumps(
            {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "expires_at": int((issued + lifetime).timestamp()),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        encoded = _encode(payload)
        signature = hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
        return f"{encoded}.{_encode(signature)}"

    def resolve(
        self,
        token: str,
        *,
        membership: Callable[[str, str], Role | None],
        now: datetime | None = None,
    ) -> Principal:
        try:
            encoded, signature = token.split(".")
            expected = hmac.new(self._key, encoded.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(_decode(signature), expected):
                raise AuthenticationError("session signature is invalid")
            raw: object = json.loads(_decode(encoded))
        except (ValueError, UnicodeError, binascii.Error, TypeError) as exc:
            if isinstance(exc, AuthenticationError):
                raise
            raise AuthenticationError("session signature or format is invalid") from exc
        if not isinstance(raw, dict):
            raise AuthenticationError("session format is invalid")
        payload = cast(Mapping[str, object], raw)
        if set(payload) != {"user_id", "tenant_id", "expires_at"}:
            raise AuthenticationError("session format is invalid")
        user_id, tenant_id, expires_at = (
            payload["user_id"],
            payload["tenant_id"],
            payload["expires_at"],
        )
        if (
            not isinstance(user_id, str)
            or not user_id.strip()
            or not isinstance(tenant_id, str)
            or not tenant_id.strip()
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
        ):
            raise AuthenticationError("session format is invalid")
        checked = now if now is not None else datetime.now(UTC)
        if checked.tzinfo is None:
            raise ValueError("session clock must be timezone-aware")
        if checked.timestamp() >= expires_at:
            raise AuthenticationError("session expired")
        role = membership(user_id, tenant_id)
        if role is None:
            raise AuthenticationError("clinic membership is inactive")
        return Principal(user_id=user_id, tenant_id=tenant_id, role=role)

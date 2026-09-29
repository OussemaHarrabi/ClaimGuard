"""Signed sessions identify a user, while current membership grants the role."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from claimguard.clinic.access import Role
from claimguard.clinic.session import AuthenticationError, SessionSigner

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


def test_session_resolves_current_membership_not_a_token_role() -> None:
    signer = SessionSigner(b"s" * 32)
    token = signer.issue("user-1", "clinic-a", now=NOW)

    principal = signer.resolve(
        token,
        membership=lambda user_id, tenant_id: (
            Role.RCM_LEAD if (user_id, tenant_id) == ("user-1", "clinic-a") else None
        ),
        now=NOW + timedelta(minutes=1),
    )

    assert principal.user_id == "user-1"
    assert principal.tenant_id == "clinic-a"
    assert principal.role is Role.RCM_LEAD


def test_revoked_membership_is_rejected() -> None:
    signer = SessionSigner(b"s" * 32)
    token = signer.issue("user-1", "clinic-a", now=NOW)

    with pytest.raises(AuthenticationError, match="membership"):
        signer.resolve(token, membership=lambda _user, _tenant: None, now=NOW)


def test_tampered_or_expired_session_is_rejected() -> None:
    signer = SessionSigner(b"s" * 32)
    token = signer.issue("user-1", "clinic-a", now=NOW, lifetime=timedelta(minutes=5))

    def membership(_user: str, _tenant: str) -> Role:
        return Role.RCM_REVIEWER

    with pytest.raises(AuthenticationError, match="signature"):
        signer.resolve(token + "x", membership=membership, now=NOW)
    with pytest.raises(AuthenticationError, match="expired"):
        signer.resolve(token, membership=membership, now=NOW + timedelta(minutes=6))


def test_short_signing_key_is_refused() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        SessionSigner(b"short")

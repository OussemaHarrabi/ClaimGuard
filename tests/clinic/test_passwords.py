"""Clinic passwords are salted, verifiable, and never stored as plaintext."""

from __future__ import annotations

from claimguard.clinic.passwords import hash_password, verify_password


def test_password_hash_is_salted_and_verifiable() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first != second
    assert "correct horse battery staple" not in first
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong", first)


def test_malformed_password_hash_fails_closed() -> None:
    assert not verify_password("anything", "plain-text")

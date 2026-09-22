"""Shared fixtures for the ``claimguard.edu`` engine tests.

The rule catalogue is a small read-only *input* our engine needs, so it is
vendored under ``fixtures/pack_reference/`` (12 KB, byte-identical to the mentor
pack, checksums in ``PROVENANCE.json``). That keeps the engine's own tests
runnable in CI, where the mentor pack itself — large delivered reference
material — is deliberately absent.

Tests that need the pack's gold labels say so with ``@requires_pack`` and skip
when the pack is not checked out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from claimguard.edu.engine import evaluate_claim
from claimguard.edu.policy import RuleContext

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = REPO_ROOT / "ClaimGuardAI_Student_Starter_Pack" / "ClaimGuardAI_Student_Starter_Pack"
RULES_DIR = Path(__file__).resolve().parent / "fixtures" / "pack_reference"
DEVELOPMENT_DIR = PACK_ROOT / "data" / "development"

#: Gold labels and the strict scorer live in the mentor pack, which is not
#: tracked in git. Those checks run locally (``make edu-conformance``) and as a
#: pre-submission gate, not in CI.
requires_pack = pytest.mark.skipif(
    not (DEVELOPMENT_DIR / "expected_results.jsonl").is_file(),
    reason="mentor starter pack absent (delivered reference material, not tracked in git)",
)

_context_cache: RuleContext | None = None


def rules_context() -> RuleContext:
    """The pack rule catalogues, loaded once per test session."""
    global _context_cache
    if _context_cache is None:
        _context_cache = RuleContext.from_rules_dir(RULES_DIR)
    return _context_cache


def base_claim() -> dict[str, Any]:
    """A clean claim that satisfies every rule of the pack rulebook.

    One consultation line under EDU-BASIC: no authorization or document is
    required, the submission is 10 days after the service, and the amounts,
    quantities and identifiers are all consistent — so R001-R015 either PASS or
    are NOT_APPLICABLE.
    """
    return {
        "schema_version": "1.0.0",
        "claim_id": "CG-TEST-0001",
        "invoice_number": "INV-TEST-0001",
        "patient_id": "PAT-TEST",
        "member_id": "MEM-TEST",
        "provider_id": "EDU-PROV-01",
        "payer_id": "EDU-PAYER",
        "policy_id": "EDU-BASIC",
        "diagnosis_code": "DX-EDU-01",
        "submission_date": "2026-03-20",
        "currency": "SAR",
        "total_amount": 190,
        "coverage": {
            "coverage_id": "COV-TEST-0001",
            "status": "active",
            "beneficiary_patient_id": "PAT-TEST",
            "member_id": "MEM-TEST",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        "lines": [line()],
        "authorizations": [],
        "attachments": [],
        "notes": "Synthetic claim for tests. No real patient or payer information.",
    }


def line(
    line_id: str = "L1",
    service_code: str | None = "SVC-CONSULT",
    service_date: str | None = "2026-03-10",
    quantity: Any = 1,
    unit_price: Any = 190,
    net_amount: Any = 190,
    authorization_id: str | None = None,
    modifier: str | None = None,
) -> dict[str, Any]:
    """One transport-conformant service line."""
    return {
        "line_id": line_id,
        "service_code": service_code,
        "service_date": service_date,
        "modifier": modifier,
        "quantity": quantity,
        "unit_price": unit_price,
        "net_amount": net_amount,
        "authorization_id": authorization_id,
    }


def authorization(
    authorization_id: str = "AUTH-TEST-1",
    patient_id: str = "PAT-TEST",
    service_code: str = "SVC-IMAGE",
    status: str = "approved",
    valid_from: str | None = "2026-03-01",
    valid_to: str | None = "2026-03-31",
    max_quantity: Any = 1,
) -> dict[str, Any]:
    """One authorization sidecar record."""
    return {
        "authorization_id": authorization_id,
        "patient_id": patient_id,
        "service_code": service_code,
        "status": status,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "max_quantity": max_quantity,
    }


def attachment(
    attachment_id: str = "DOC-TEST-1",
    document_type: str = "imaging-report",
    patient_id: str = "PAT-TEST",
    service_code: str = "SVC-IMAGE",
    service_date: str = "2026-03-10",
    document_status: str = "final",
    text: str = "SYNTHETIC TRAINING DOCUMENT.",
) -> dict[str, Any]:
    """One attachment inventory entry."""
    return {
        "attachment_id": attachment_id,
        "type": document_type,
        "patient_id": patient_id,
        "service_code": service_code,
        "service_date": service_date,
        "document_status": document_status,
        "text": text,
    }


def imaging_claim() -> dict[str, Any]:
    """A claim with one SVC-IMAGE line — authorization AND document required."""
    claim = base_claim()
    claim["lines"] = [
        line(
            service_code="SVC-IMAGE",
            unit_price=1500,
            net_amount=1500,
            authorization_id="AUTH-TEST-1",
        )
    ]
    claim["total_amount"] = 1500
    claim["authorizations"] = [authorization()]
    claim["attachments"] = [attachment()]
    return claim


def record(claim: dict[str, Any], rule_id: str) -> dict[str, Any]:
    """Evaluate one claim and return its single record for ``rule_id``."""
    records = {entry["rule_id"]: entry for entry in evaluate_claim(claim, rules_context())}
    assert rule_id in records, f"{rule_id} missing from engine output"
    return records[rule_id]


def status_of(claim: dict[str, Any], rule_id: str) -> str:
    """Evaluate one claim and return the status reported for ``rule_id``."""
    return str(record(claim, rule_id)["status"])


def all_statuses(claim: dict[str, Any]) -> dict[str, str]:
    """Rule id → status for all 15 rules of ``claim``."""
    return {
        str(entry["rule_id"]): str(entry["status"])
        for entry in evaluate_claim(claim, rules_context())
    }

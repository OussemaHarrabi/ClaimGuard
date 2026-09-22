"""Transport and result-contract tests for ``claimguard.edu.envelope``.

The envelope validator must accept exactly what the pack's teaching transport
contract accepts and reject the defects the pack calls ingestion errors
(docs/03_Data_Dictionary.md, "Nulls, keys and transport errors").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from claimguard.edu.envelope import (
    RESULT_KEYS,
    ClaimEnvelope,
    ContractError,
    ResultRecord,
    Status,
    TransportError,
    load_jsonl,
    load_transport_claims,
    validate_transport,
)
from pydantic import ValidationError

from tests.edu import base_claim, line


def test_valid_envelope_is_accepted_and_typed() -> None:
    claim = base_claim()
    envelope = validate_transport(claim)
    assert isinstance(envelope, ClaimEnvelope)
    assert envelope.claim_id == "CG-TEST-0001"
    assert envelope.coverage.status == "active"
    assert [service.line_id for service in envelope.lines] == ["L1"]


def test_null_business_values_are_transport_valid() -> None:
    """Nullables are permitted by transport even when a payer rule demands them."""
    claim = base_claim()
    claim["member_id"] = None
    claim["invoice_number"] = None
    claim["diagnosis_code"] = None
    claim["total_amount"] = None
    claim["lines"][0]["quantity"] = None
    validate_transport(claim)


@pytest.mark.parametrize("key", ["schema_version", "claim_id", "notes", "currency"])
def test_blank_required_string_is_rejected(key: str) -> None:
    claim = base_claim()
    claim[key] = ""
    with pytest.raises(TransportError, match=key):
        validate_transport(claim)


def test_missing_envelope_key_is_rejected() -> None:
    claim = base_claim()
    del claim["coverage"]
    with pytest.raises(TransportError, match="envelope keys"):
        validate_transport(claim)


def test_extra_envelope_key_is_rejected() -> None:
    claim = base_claim()
    claim["payer_name"] = "EDU-PAYER"
    with pytest.raises(TransportError, match="envelope keys"):
        validate_transport(claim)


def test_invalid_submission_date_is_rejected() -> None:
    claim = base_claim()
    claim["submission_date"] = "20-03-2026"
    with pytest.raises(TransportError, match="submission date"):
        validate_transport(claim)


def test_invalid_service_date_is_rejected() -> None:
    claim = base_claim()
    claim["lines"][0]["service_date"] = "2026-13-45"
    with pytest.raises(TransportError, match="service date"):
        validate_transport(claim)


def test_duplicate_line_id_is_rejected() -> None:
    claim = base_claim()
    claim["lines"].append(line(service_code="SVC-LAB", unit_price=120, net_amount=120))
    with pytest.raises(TransportError, match="Duplicate line ID"):
        validate_transport(claim)


def test_empty_lines_array_is_rejected() -> None:
    claim = base_claim()
    claim["lines"] = []
    with pytest.raises(TransportError, match="nonempty lines"):
        validate_transport(claim)


def test_boolean_quantity_is_not_a_number() -> None:
    claim = base_claim()
    claim["lines"][0]["quantity"] = True
    with pytest.raises(TransportError, match="quantity"):
        validate_transport(claim)


def test_missing_line_key_is_rejected() -> None:
    claim = base_claim()
    del claim["lines"][0]["net_amount"]
    with pytest.raises(TransportError, match="Line keys"):
        validate_transport(claim)


def test_missing_coverage_key_is_rejected() -> None:
    claim = base_claim()
    del claim["coverage"]["end_date"]
    with pytest.raises(TransportError, match="Coverage keys"):
        validate_transport(claim)


def test_authorization_number_field_must_be_numeric() -> None:
    claim = base_claim()
    claim["authorizations"] = [
        {
            "authorization_id": "AUTH-1",
            "patient_id": "PAT-TEST",
            "service_code": "SVC-IMAGE",
            "status": "approved",
            "valid_from": "2026-03-01",
            "valid_to": "2026-03-31",
            "max_quantity": "many",
        }
    ]
    with pytest.raises(TransportError, match="max_quantity"):
        validate_transport(claim)


def test_load_jsonl_parses_each_non_blank_line(tmp_path: Path) -> None:
    path = tmp_path / "claims.jsonl"
    path.write_text('{"claim_id": "CG-1"}\n\n{"claim_id": "CG-2"}\n', encoding="utf-8")
    assert load_jsonl(path) == [{"claim_id": "CG-1"}, {"claim_id": "CG-2"}]


def test_malformed_and_incomplete_lines_are_quarantined_not_dropped(tmp_path: Path) -> None:
    """Every input line is accounted for: accepted XOR quarantined (docs/03)."""
    claim = base_claim()
    defective = base_claim()
    defective["claim_id"] = "CG-TEST-0002"
    del defective["notes"]
    path = tmp_path / "claims.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(claim),
                "{not json at all",
                json.dumps(defective),
                '["not", "an", "object"]',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    accepted, quarantined = load_transport_claims(path)
    assert accepted == [claim]
    assert [error.line_number for error in quarantined] == [2, 3, 4]
    assert [error.claim_id for error in quarantined] == [None, "CG-TEST-0002", None]
    assert "malformed JSON" in quarantined[0].reason
    assert "envelope keys" in quarantined[1].reason
    assert quarantined[0].as_dict() == {
        "line_number": 2,
        "claim_id": None,
        "reason": quarantined[0].reason,
        "kind": "ingestion_error",
    }
    assert len(accepted) + len(quarantined) == 4


def _result(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "claim_id": "CG-TEST-0001",
        "rule_id": "R001",
        "rule_version": "1.0.0",
        "status": "PASS",
        "severity": "high",
        "affected_line_ids": [],
        "evidence": [{"path": "/invoice_number", "value": "INV-TEST-0001"}],
        "rule_source": "fictional-rulebook/R001@1.0.0",
        "explanation": "Required information is present.",
        "corrective_action": "",
        "confidence": None,
        "confidence_kind": "not_probabilistic",
        "requires_human_review": False,
        "method": "deterministic",
        "review_status": "unreviewed",
    }
    record.update(overrides)
    return record


def test_result_record_accepts_the_frozen_key_set() -> None:
    assert tuple(_result()) == RESULT_KEYS
    validated = ResultRecord.model_validate(_result())
    assert validated.status is Status.PASS


def test_result_record_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        ResultRecord.model_validate(_result(status="MAYBE"))


def test_result_record_rejects_extra_key() -> None:
    with pytest.raises(ValidationError):
        ResultRecord.model_validate(_result(confidence_reason="test"))


def test_result_record_requires_evidence_for_implemented_statuses() -> None:
    with pytest.raises(ValidationError, match="Evidence is required"):
        ResultRecord.model_validate(_result(evidence=[]))


def test_result_record_fail_requires_review_and_action() -> None:
    with pytest.raises(ValidationError, match="human review"):
        ResultRecord.model_validate(
            _result(status="FAIL", explanation="broken", evidence=[{"path": "/x", "value": 1}])
        )


def test_result_record_deterministic_confidence_is_null() -> None:
    with pytest.raises(ValidationError, match="confidence must be null"):
        ResultRecord.model_validate(_result(confidence=0.9))


def test_result_record_pointer_must_be_a_json_pointer() -> None:
    with pytest.raises(ValidationError, match="JSON pointer"):
        ResultRecord.model_validate(
            _result(evidence=[{"path": "invoice_number", "value": "INV-TEST-0001"}])
        )


def test_contract_error_is_a_value_error() -> None:
    assert issubclass(ContractError, ValueError)
    assert issubclass(TransportError, ValueError)

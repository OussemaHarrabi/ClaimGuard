"""Pack-conformant deterministic rule engine for the ClaimGuard teaching benchmark.

This subpackage implements the 15 fictional payer rules of
``ClaimGuardAI_Student_Starter_Pack/docs/04_Rulebook.md`` over the normalized
17-key claim envelope, producing the frozen 15-key result record per claim-rule
pair that the pack's own scorer (``src/evaluate.py``) accepts.

Layout:

*   :mod:`claimguard.edu.envelope` — transport/result contracts, value helpers
*   :mod:`claimguard.edu.evidence` — RFC 6901 pointers into the original claim
*   :mod:`claimguard.edu.policy`   — ``rules/*.json`` catalogues and rule metadata
*   :mod:`claimguard.edu.rules`    — the 15 checks, R001..R015
*   :mod:`claimguard.edu.engine`   — one claim in, 15 records out
*   :mod:`claimguard.edu.emit`     — validate + serialize the result contract
*   :mod:`claimguard.edu.run`      — the CLI (``python -m claimguard.edu.run``)

The engine is additive: it reads the pack read-only and does not touch the
application pipeline under ``claimguard/ingest``, ``claimguard/audit`` or the
existing contracts.
"""

from __future__ import annotations

from claimguard.edu.emit import make_result, serialize, validate_record
from claimguard.edu.engine import evaluate_claim, evaluate_claims
from claimguard.edu.envelope import (
    RESULT_KEYS,
    RULE_IDS,
    RULE_VERSION,
    Claim,
    ClaimEnvelope,
    ContractError,
    IngestionError,
    Result,
    ResultRecord,
    Severity,
    Status,
    TransportError,
    load_jsonl,
    load_transport_claims,
    validate_transport,
)
from claimguard.edu.evidence import EvidenceError, build_evidence, resolve
from claimguard.edu.policy import Policy, RuleContext, RuleMeta

__all__ = [
    "RESULT_KEYS",
    "RULE_IDS",
    "RULE_VERSION",
    "Claim",
    "ClaimEnvelope",
    "ContractError",
    "EvidenceError",
    "IngestionError",
    "Policy",
    "Result",
    "ResultRecord",
    "RuleContext",
    "RuleMeta",
    "Severity",
    "Status",
    "TransportError",
    "build_evidence",
    "evaluate_claim",
    "evaluate_claims",
    "load_jsonl",
    "load_transport_claims",
    "make_result",
    "resolve",
    "serialize",
    "validate_record",
    "validate_transport",
]

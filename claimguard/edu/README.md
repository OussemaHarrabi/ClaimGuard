# Deterministic Phase 1 engine

`claimguard.edu` is the authoritative validation core for the fictional ClaimGuard payer-rule catalogue. It owns normalization into the scoring envelope, execution of rules `R001` through `R015`, evidence resolution, result emission, and the bounded explanation fallback.

[Back to the project README](../../README.md)

## Authority boundary

The engine decides rule status. No language model, JEV response, frontend component, or reviewer prose may change its status, severity, evidence, or rule version.

Every accepted claim produces exactly 15 records with one status per rule:

- `PASS`
- `FAIL`
- `UNABLE_TO_ASSESS`
- `NOT_APPLICABLE`
- `NOT_IMPLEMENTED`

`UNABLE_TO_ASSESS` is not a pass. `NOT_APPLICABLE` is not missing data. The difference is part of the contract.

## Result contract

A structured result includes the claim identity, rule identity and version, status, evidence, severity, confidence semantics, corrective action, and review metadata. Evidence uses RFC 6901 JSON Pointer paths and the exact original values at those paths.

Deterministic checks emit `confidence: null` and `confidence_kind: not_probabilistic`. ClaimGuard does not disguise rule output as a calibrated probability.

The canonical implementation is split across:

| File or directory | Responsibility |
|---|---|
| `envelope.py` | Canonical 17-key claim envelope |
| `engine.py` | Fifteen-check execution and invariants |
| `rules/` | Rule implementations `R001`–`R015` |
| `policy.py` | Versioned fictional policy catalogue |
| `evidence.py` | Evidence resolution and validation |
| `emit.py` | Stable structured output |
| `intake/` | CSV and FHIR projections |
| `explain/` | Deterministic fallback, optional provider, and verifier |
| `judge/` | JEV advisory sidecar, outside the authoritative record |

## Inputs

- **Envelope JSON:** one canonical object.
- **Split CSV:** five required tables reconstructed into the same envelope.
- **FHIR R4:** a Bundle plus sidecar for scoring fields that FHIR does not carry reliably.

Input validation happens before rule execution. Unsupported or missing source information is reported rather than invented. See [the sample package guide](../../examples/phase1/README.md).

## Run and verify

From the repository root:

```powershell
uv run claimguard evaluate --split all
uv run claimguard report --split development --output docs/verification/EDU-EVALUATION-REPORT.md
uv run python scripts/edu_conformance.py
uv run pytest tests/edu tests/edu_edges tests/edu_intake tests/edu_explain tests/edu_conformance
```

The mentor pack can be selected with `CLAIMGUARD_PACK_ROOT`. A rule catalogue directory can be selected with `CLAIMGUARD_RULES_DIR`. The committed reference catalogue under `tests/edu/fixtures/pack_reference/` keeps a fresh clone runnable.

## Change discipline

When a rule changes:

1. Confirm the versioned catalogue is the authority.
2. Add positive, negative, boundary, missing-data, and evidence-resolution tests.
3. Run the independent conformance harness, not only unit tests.
4. Regenerate reported metrics rather than editing numbers manually.
5. Document a semantic change and its compatibility impact.

Do not add network calls to the deterministic path. Do not let explanation or judge output enter the 15-key result record.

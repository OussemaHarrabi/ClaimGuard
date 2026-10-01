# Verification and evidence scripts

These scripts regenerate evidence used by the project documentation and demonstration. Run them from the repository root through `uv` so they use the locked environment.

[Back to the project README](../README.md)

| Script | Purpose | Typical command |
|---|---|---|
| `sample_run.py` | Reproducible claim submission, findings, decision, and workflow transcript | `uv run python scripts/sample_run.py` |
| `edu_conformance.py` | Independent rule-result conformance check | `uv run python scripts/edu_conformance.py --all` |
| `edu_report.py` | Generate the Markdown evaluation report | Prefer `uv run claimguard report --split development --output docs/verification/EDU-EVALUATION-REPORT.md` |
| `detection_metrics.py` | Recompute category metrics, false-positive rate, and latency | `uv run python scripts/detection_metrics.py --help` |
| `adversarial_cases.py` | Execute boundary and mutation cases | `uv run python scripts/adversarial_cases.py` |
| `fhir_example.py` | Reproduce FHIR projection and its unsupported-field report | `uv run python scripts/fhir_example.py --help` |
| `audit_replay.py` | Reconstruct one persisted run and verify the hash chain | `uv run python scripts/audit_replay.py --run-id RUN_ID` |
| `ai_ablation.py` | Compare deterministic fallback and optional model assistance | `uv run python scripts/ai_ablation.py --help` |
| `make_demo_claims.py` | Build or verify the presentation claim set | `uv run python scripts/make_demo_claims.py --check` |

Use `--help` before running a script against a different pack, split, rule directory, output directory, or run ID.

## Evidence rules

- A script should fail with a non-zero exit code when its claimed invariant is false.
- Generated reports must record inputs, catalogue versions, and relevant environment facts.
- Do not hand-edit a generated metric to make documentation pass.
- Keep live model calls opt-in and clearly separated from deterministic checks.
- Never pass real patient data or credentials to a script.
- Do not commit large scratch artifacts unless the repository deliberately preserves them as evidence.

The mentor pack is optional local reference material and may be selected with `CLAIMGUARD_PACK_ROOT` or command-line arguments. The committed reference catalogue keeps core tests and the demo runnable in a fresh clone.

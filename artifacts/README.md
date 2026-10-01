# Generated artifacts

This directory contains reproducible outputs from ClaimGuard's verification and architecture tooling. It is evidence generated from source, not an additional source of application logic.

[Back to the project README](../README.md)

| Path | Contents | Regenerator |
|---|---|---|
| `edu/` | Per-split predictions, scorer metrics, and conformance reports | `uv run claimguard evaluate --split all` |
| `edu-report/` | Inputs used for generated evaluation reporting | `uv run claimguard report ...` |
| `sample-run/` | Reproducible end-to-end sample output | `uv run python scripts/sample_run.py` |
| `ai-ablation/` | Deterministic-versus-assisted explanation measurements | `uv run python scripts/ai_ablation.py` |
| `claimguard-archify*` and architecture exports | Visual architecture sources and render checks | Diagram workflow under `reports/phase1-architecture/` |

## Rules

- Treat generated files as snapshots tied to their recorded inputs and versions.
- Regenerate rather than hand-edit metrics.
- Review diffs for unexpected input, catalogue, model, or environment changes.
- Keep scratch output and large provider downloads out of Git.
- Never place credentials or real patient data here.
- A stale artifact does not override current code or a newer generated report.

Published numbers should link to the command and artifact that produced them. The root README's synthetic benchmark results are additionally documented under `docs/verification/`.

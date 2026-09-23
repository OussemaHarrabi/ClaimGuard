"""The sample run is demo evidence, so the property that matters is that it bites.

A transcript that only ever shows a clean claim proves nothing about the system, and
a transcript produced by hand is not evidence. These tests pin two things: that the
run refuses loudly when its inputs are missing, and that its default claim really
does fail at least one check.

The full end-to-end run needs PostgreSQL and the mentor pack, so it lives in
``docs/verification/REPRODUCIBLE-SAMPLE-RUN.md`` as a captured transcript rather
than as a CI test.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "sample_run.py"
PACK_ROOT = REPO_ROOT / "ClaimGuardAI_Student_Starter_Pack" / "ClaimGuardAI_Student_Starter_Pack"

requires_pack = pytest.mark.skipif(
    not (PACK_ROOT / "data" / "development" / "claims.jsonl").is_file(),
    reason="mentor starter pack absent (delivered reference material, not tracked in git)",
)


def load_script() -> ModuleType:
    """Import ``scripts/sample_run.py`` by path — ``scripts/`` is not an importable package."""
    spec = importlib.util.spec_from_file_location("claimguard_sample_run", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sample_run() -> ModuleType:
    return load_script()


def test_refuses_loudly_when_the_pack_is_missing(
    sample_run: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A demo that silently degrades would be worse than no demo, so it must refuse."""
    code = sample_run.main(
        ["--pack-root", str(tmp_path / "absent"), "--workdir", str(tmp_path / "work")]
    )
    captured = capsys.readouterr()
    combined = (captured.out + captured.err).lower()
    assert code == sample_run.EXIT_REFUSED
    assert "refused" in combined
    assert "pack" in combined, "say which input was missing"


@requires_pack
def test_the_default_claim_is_a_real_failure_not_a_happy_path(
    sample_run: ModuleType,
) -> None:
    """If the default claim ever passes everything, the demo stops demonstrating."""
    from claimguard.edu.engine import evaluate_claim
    from claimguard.edu.policy import RuleContext

    wanted = sample_run.DEFAULT_CLAIM_ID
    claims = [
        json.loads(line)
        for line in (PACK_ROOT / "data" / "development" / "claims.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    claim = next((c for c in claims if c["claim_id"] == wanted), None)
    assert claim is not None, f"the default claim {wanted} is not in the development split"

    context = RuleContext.from_rules_dir(PACK_ROOT / "rules")
    statuses = {record["rule_id"]: record["status"] for record in evaluate_claim(claim, context)}
    failed = sorted(rule_id for rule_id, status in statuses.items() if status == "FAIL")

    assert len(statuses) == 15, "every rule must report exactly once per claim"
    assert failed, (
        f"the demo claim {wanted} passes every check, so the demo would show nothing. "
        "Pick a claim that fails at least one rule."
    )


def test_the_transcript_states_what_the_run_does_not_prove(sample_run: ModuleType) -> None:
    """The honesty section is a product requirement, not decoration — it must exist."""
    source = SCRIPT.read_text(encoding="utf-8")
    lowered = source.lower()
    for statement in (
        "payer",
        "synthetic",
        "instructional oracle",
        "not_implemented",
        "immutab",
    ):
        assert statement in lowered, (
            f"the transcript must keep its honesty statement about {statement!r}; "
            "removing it would let the demo overclaim"
        )

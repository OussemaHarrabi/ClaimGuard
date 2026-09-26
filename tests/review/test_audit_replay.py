"""Tests for the audit replay (``scripts/audit_replay.py`` — Phase-1 gap G3).

The replay has two halves, and so does this module.

**Pure** (no database, no catalogue, always run):

*   ``compare_record`` — the field-by-field comparison of one stored record
    against its replay, including how a model-drafted ``explanation`` is told
    apart from a genuine disagreement.
*   ``first_broken_link`` — the ledger-linkage walk, including the honest limit
    that a row cut from the tail leaves no trace.

**Database-backed** (marked ``integration``; skipped automatically when
PostgreSQL is unreachable, see :mod:`tests.review`): the four tests decorated
with ``@requires_db`` below. They need a real run, because the properties under
test are "the stored run is reproduced from the stored envelope" and "the stored
results were not used as an input" — neither can be shown against a fixture.

The database tests use the committed rule catalogue
(``tests/edu/fixtures/pack_reference``) and the deterministic explanation
provider, so they need neither the mentor pack nor a model.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from claimguard.edu.envelope import RESULT_KEYS
from claimguard.review import audit_events
from claimguard.review.models import ExplanationProvenance, RuleRun
from claimguard.review.store import ReviewStore, envelope_digest
from scripts import audit_replay
from scripts.audit_replay import (
    EXIT_OK,
    EXIT_REFUSED,
    EXPLANATION_DIFFERS,
    EXPLANATION_MODEL_DRAFTED,
    EXPLANATION_REPRODUCED,
    MISSING_RECORD,
    ChainLink,
    compare_record,
    contiguous_expected_prev,
    first_broken_link,
    replay_run,
    run_event_mismatches,
)
from sqlalchemy import Engine

from tests.edu import RULES_DIR
from tests.review.conftest import FAILING_RULE, TEST_DSN, Sandbox, requires_db

# ---------------------------------------------------------------------------
# Hand-built inputs
# ---------------------------------------------------------------------------

#: One contract-shaped 15-key record: the pair the comparison is fed.
_BASE_RECORD: Mapping[str, Any] = {
    "claim_id": "CG-REPLAY-TEST",
    "rule_id": FAILING_RULE,
    "rule_version": "1.0.0",
    "status": "FAIL",
    "severity": "high",
    "affected_line_ids": ["L1"],
    "evidence": [{"path": "/coverage/end_date", "value": "2026-03-09"}],
    "rule_source": f"fictional-rulebook/{FAILING_RULE}@1.0.0",
    "explanation": "[deterministic] R003 reports FAIL (severity high) for claim CG-REPLAY-TEST.",
    "corrective_action": "Verify coverage applicable on the service date with the source records.",
    "confidence": None,
    "confidence_kind": "not_probabilistic",
    "requires_human_review": True,
    "method": "deterministic",
    "review_status": "unreviewed",
}


def record(**overrides: Any) -> dict[str, Any]:
    """A contract-shaped 15-key record, with the named fields overridden."""
    values = dict(_BASE_RECORD)
    values.update(overrides)
    return values


def provenance(**overrides: Any) -> ExplanationProvenance:
    """Explanation provenance for one record, deterministic unless overridden."""
    values: dict[str, Any] = {
        "rule_id": FAILING_RULE,
        "seq": 3,
        "source": "deterministic",
        "provider": "template",
        "rewritten": True,
        "fallback_used": False,
        "correction_recommendation": "Verify coverage applicable on the service date.",
        "cited_evidence_paths": ["/coverage/end_date"],
        "security_decision": "accept",
        "receipt_sha256": None,
        "rejection_reasons": [],
        "declined_reason": None,
    }
    values.update(overrides)
    return ExplanationProvenance.model_validate(values)


#: The provenance code a run event carries for the ``run`` fixture below.
RUN_PROVENANCE: Final = f"input_sha256={'a' * 64} prompt_version=none actor=api-submit"


def link(index: int, prev_hash: str, chain_hash: str, **overrides: Any) -> ChainLink:
    """One hand-built ledger link (the walk reads only ``prev_hash``/``chain_hash``)."""
    values: dict[str, Any] = {
        "index": index,
        "event_id": f"0000000{index}-0000-0000-0000-00000000000{index}",
        "at": f"2026-01-0{index} 00:00:00+00",
        "kind": audit_events.RUN_KIND,
        "trace_id": "b" * 32,
        "decision": None,
        "reason_code": RUN_PROVENANCE,
        "finding_ids": (FAILING_RULE,),
        "rule_version": "1.0.0",
        "model_version": "deterministic-engine/1.0.0",
        "prev_hash": prev_hash,
        "chain_hash": chain_hash,
    }
    values.update(overrides)
    return ChainLink(**values)


def run(**overrides: Any) -> RuleRun:
    """The run row a hand-built run event claims to describe."""
    values: dict[str, Any] = {
        "run_id": "RUN-" + "0" * 32,
        "claim_id": "CG-REPLAY-TEST",
        "version": 1,
        "input_hash": "a" * 64,
        "trace_id": "b" * 32,
        "rule_version": "1.0.0",
        "model_version": "deterministic-engine/1.0.0",
        "prompt_version": "none",
        "initiated_by": "api-submit",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return RuleRun.model_validate(values)


def test_the_hand_built_record_is_the_frozen_fifteen_key_contract() -> None:
    """The comparison is only meaningful over the contract's exact key set."""
    assert set(_BASE_RECORD) == set(RESULT_KEYS)


# ---------------------------------------------------------------------------
# The comparison (pure)
# ---------------------------------------------------------------------------


def test_an_identical_pair_reproduces_with_no_differing_fields() -> None:
    comparison = compare_record(record(), record(), provenance())
    assert comparison.agrees
    assert comparison.differing_fields == ()
    assert comparison.explanation == EXPLANATION_REPRODUCED
    assert comparison.rule_id == FAILING_RULE
    assert comparison.stored_status == "FAIL"


def test_a_deliberately_mismatched_pair_fails_and_names_the_field() -> None:
    """A decision field that changed is a defect, and it is named, not summarised."""
    comparison = compare_record(record(), record(severity="low", status="PASS"), provenance())
    assert not comparison.agrees
    assert comparison.differing_fields == ("status", "severity")
    assert comparison.explanation == EXPLANATION_REPRODUCED


def test_a_different_evidence_value_is_a_disagreement() -> None:
    """Evidence is compared by value, not by the pointer alone."""
    replayed = record(evidence=[{"path": "/coverage/end_date", "value": "2026-03-10"}])
    comparison = compare_record(record(), replayed, provenance())
    assert comparison.differing_fields == ("evidence",)
    assert not comparison.agrees


def test_a_model_drafted_explanation_is_not_a_disagreement() -> None:
    """The wording may come from a model; the provenance says so, and replay says so."""
    replayed = record(explanation="[deterministic] R003 reports FAIL (severity high).")
    comparison = compare_record(
        record(explanation="[model] A model drafted this sentence for R003."),
        replayed,
        provenance(source="model", provider="test-model"),
    )
    assert comparison.explanation == EXPLANATION_MODEL_DRAFTED
    assert comparison.differing_fields == ()
    assert comparison.agrees


def test_an_unexplained_explanation_difference_is_a_disagreement() -> None:
    """Without provenance saying a model wrote it, different text is a defect."""
    comparison = compare_record(
        record(explanation="[deterministic] something else"),
        record(),
        provenance(),
    )
    assert comparison.explanation == EXPLANATION_DIFFERS
    assert not comparison.agrees


def test_a_record_missing_from_either_side_is_reported_not_skipped() -> None:
    absent_from_run = compare_record(None, record(), None)
    absent_from_replay = compare_record(record(), None, provenance())
    assert absent_from_run.differing_fields == (MISSING_RECORD,)
    assert absent_from_replay.differing_fields == (MISSING_RECORD,)
    assert not absent_from_run.agrees
    assert not absent_from_replay.agrees
    assert absent_from_run.rule_id == FAILING_RULE


# ---------------------------------------------------------------------------
# The ledger walk (pure)
# ---------------------------------------------------------------------------


def test_an_intact_chain_of_links_has_no_break() -> None:
    events = [link(1, "genesis", "aa"), link(2, "aa", "bb"), link(3, "bb", "cc")]
    assert first_broken_link(events, contiguous_expected_prev(events, "genesis")) is None


def test_a_row_removed_from_the_middle_breaks_the_link() -> None:
    """The gap is detectable: the surviving row names a hash that is not there."""
    intact = [link(1, "genesis", "aa"), link(2, "aa", "bb"), link(3, "bb", "cc")]
    with_the_middle_row_cut = [intact[0], intact[2]]
    assert first_broken_link(with_the_middle_row_cut, ("genesis", "dd")) == 1


def test_a_row_removed_from_the_tail_leaves_no_trace() -> None:
    """The stated limit: nothing inside the ledger references a row that is gone."""
    intact = [link(1, "genesis", "aa"), link(2, "aa", "bb"), link(3, "bb", "cc")]
    assert first_broken_link(intact[:2], ("genesis", "aa")) is None


def test_a_row_that_does_not_chain_to_the_ledger_before_it_is_a_break() -> None:
    """The anchor comes from the live ledger: a forged first link does not verify."""
    assert first_broken_link([link(1, "genesis", "aa")], ("9f9f",)) == 0
    assert first_broken_link([link(1, "9f9f", "aa")], ("9f9f",)) is None


def test_other_runs_between_two_events_are_not_a_break() -> None:
    """The ledger is ONE global chain, so a run's events need not be adjacent.

    This is the normal case in a shared ledger and the bug this test exists for:
    a run whose decision arrives after unrelated activity chains to that other
    row, not to its own first event. Comparing a run's events against each other
    reported a false break on every real run.
    """
    events = [link(1, "aaa", "bbb"), link(2, "zzz", "ccc")]
    assert first_broken_link(events, ("aaa", "zzz")) is None
    # ...and the global predecessor is exactly what makes it valid.
    assert first_broken_link(events, ("aaa", "bbb")) == 1


def test_a_run_event_that_describes_its_run_is_accepted() -> None:
    """The ledger is a reconstructable history: its versions, hash and actor are the run's."""
    assert run_event_mismatches([link(1, "genesis", "aa")], run(), [FAILING_RULE]) == ()


def test_a_run_event_that_does_not_describe_its_run_is_inconsistent() -> None:
    """Each field the auditor would read out of the ledger is checked, not trusted."""
    attention = [FAILING_RULE]

    wrong_hash = link(1, "genesis", "aa", reason_code=RUN_PROVENANCE.replace("a" * 64, "f" * 64))
    problems = run_event_mismatches([wrong_hash], run(), attention)
    assert len(problems) == 1
    assert "input_sha256" in problems[0]

    wrong_actor = link(
        1, "genesis", "aa", reason_code=RUN_PROVENANCE.replace("api-submit", "someone-else")
    )
    assert "actor" in run_event_mismatches([wrong_actor], run(), attention)[0]

    wrong_versions = link(1, "genesis", "aa", model_version="some-other-engine/9.9.9")
    assert "model_version" in run_event_mismatches([wrong_versions], run(), attention)[0]

    wrong_findings = link(1, "genesis", "aa", finding_ids=())
    assert "finding_ids" in run_event_mismatches([wrong_findings], run(), attention)[0]


def test_a_run_with_no_validated_event_is_inconsistent() -> None:
    """A decision event is not the run's own event, however well it chains."""
    decision_only = link(
        1, "genesis", "aa", kind=audit_events.DECISION_KIND, decision="confirm_issue"
    )
    assert run_event_mismatches([decision_only], run(), [FAILING_RULE]) == (
        "the run has no 'validated' ledger event",
    )


# ---------------------------------------------------------------------------
# End to end (needs PostgreSQL)
# ---------------------------------------------------------------------------


async def submit(client: httpx.AsyncClient, envelope: dict[str, Any]) -> str:
    """Submit one envelope through the review API and return its run id."""
    response = await client.post("/v1/claims", json={"claim": envelope})
    assert response.status_code == 201, response.text
    return str(response.json()["run"]["run_id"])


def drifted_catalogue(tmp_path: Path, severity: str) -> Path:
    """A copy of the committed catalogue with one rule's severity changed."""
    target = tmp_path / "rules"
    target.mkdir()
    for source in RULES_DIR.iterdir():
        (target / source.name).write_bytes(source.read_bytes())
    path = target / "rules.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for entry in manifest:
        if entry["rule_id"] == FAILING_RULE:
            entry["severity"] = severity
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


@pytest.mark.integration
@requires_db
async def test_a_stored_run_replays_from_its_own_envelope_and_verifies_its_ledger(
    client: httpx.AsyncClient, store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    """The whole point: a past run is reconstructed, and the ledger that recorded it verifies."""
    envelope = sandbox.coverage_lapse()
    run_id = await submit(client, envelope)

    report = replay_run(store=store, engine=engine, run_id=run_id, rules_dir=RULES_DIR)

    assert report.hash_matches
    assert report.recomputed_input_hash == envelope_digest(envelope)
    assert report.stored_input_hash == report.run.input_hash
    assert report.envelope_keys == 17
    assert report.catalogue.rules_dir == str(RULES_DIR)
    assert report.catalogue.rules == 15
    assert report.agreements == 15
    assert report.disagreements == ()
    assert [comparison.rule_id for comparison in report.comparisons] == [
        f"R{index:03d}" for index in range(1, 16)
    ]
    assert report.chain.ok
    assert [event.kind for event in report.chain.events] == [audit_events.RUN_KIND]
    assert report.chain.content_broken == ()
    assert report.chain.link_broken_index is None
    assert report.chain.run_event_mismatches == ()
    assert report.chain.run_event_provenance["input_sha256"] == report.recomputed_input_hash
    assert report.chain.run_event_provenance["actor"] == report.run.initiated_by
    assert report.exit_code == EXIT_OK

    transcript = audit_replay.render_transcript(report)
    assert run_id in transcript
    assert "15/15 records reproduced" in transcript
    assert "VERIFIED" in transcript


@pytest.mark.integration
@requires_db
async def test_the_walk_finds_the_decision_event_and_its_link(
    client: httpx.AsyncClient, store: ReviewStore, engine: Engine, sandbox: Sandbox
) -> None:
    """A human action is part of the reconstructable history, chained to the run event."""
    envelope = sandbox.coverage_lapse()
    run_id = await submit(client, envelope)
    decided = await client.post(
        f"/v1/runs/{run_id}/decisions",
        json={
            "rule_id": FAILING_RULE,
            "action": "confirm_issue",
            "actor": "rev-1",
            "reason": "checked the source record",
        },
    )
    assert decided.status_code == 201, decided.text

    report = replay_run(store=store, engine=engine, run_id=run_id, rules_dir=RULES_DIR)

    assert [event.kind for event in report.chain.events] == [
        audit_events.RUN_KIND,
        audit_events.DECISION_KIND,
    ]
    run_event, decision_event = report.chain.events
    assert decision_event.prev_hash == run_event.chain_hash
    assert decision_event.decision == "confirm_issue"
    assert report.chain.ok
    assert report.agreements == 15
    assert report.exit_code == EXIT_OK


@pytest.mark.integration
@requires_db
async def test_a_replay_with_a_drifted_catalogue_fails_and_names_the_check(
    client: httpx.AsyncClient,
    store: ReviewStore,
    engine: Engine,
    sandbox: Sandbox,
    tmp_path: Path,
) -> None:
    """A real divergence — the engine's inputs changed — is a failure, not a warning.

    This is the deliberate-mismatch case at end-to-end scale: the run is genuine,
    the ledger is intact, and only the catalogue the replay runs with differs. The
    replay must fail, name the rule, and leave the ledger verdict alone.
    """
    envelope = sandbox.coverage_lapse()
    run_id = await submit(client, envelope)
    catalogue = drifted_catalogue(tmp_path, severity="low")

    report = replay_run(store=store, engine=engine, run_id=run_id, rules_dir=catalogue)

    assert report.hash_matches
    assert report.catalogue.rules_dir == str(catalogue)
    assert report.agreements == 14
    assert [comparison.rule_id for comparison in report.disagreements] == [FAILING_RULE]
    assert "severity" in report.disagreements[0].differing_fields
    assert report.disagreements[0].stored_status == "FAIL"
    assert report.chain.ok  # the ledger is untouched; the replay is what disagrees
    assert report.exit_code != EXIT_OK


@pytest.mark.integration
@requires_db
def test_the_cli_refuses_an_unknown_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The refusal contract: exit 2 and the reason on stderr, never a traceback.

    Points the catalogue at the committed copy on purpose: without it the CLI
    refuses on the catalogue before it ever looks up the run, so this would assert
    the wrong refusal wherever the mentor pack is absent (CI, for instance).
    """
    monkeypatch.setattr(audit_replay, "resolve_dsn", lambda: TEST_DSN)
    catalogued = [
        "--run-id",
        "RUN-00000000000000000000000000000000",
        "--rules-dir",
        str(Path(__file__).resolve().parents[2] / "tests" / "edu" / "fixtures" / "pack_reference"),
    ]
    assert audit_replay.main(catalogued) == EXIT_REFUSED
    assert "no such run" in capsys.readouterr().err

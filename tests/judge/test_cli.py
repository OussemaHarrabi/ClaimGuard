"""The CLI: offline by default, and honest about which of the three states it is in.

The offline run is the one that matters today — there is no key yet — so it is
asserted twice: the sidecar must be written with every assessment ``skipped``,
the results file must come back byte-identical, and ``urlopen`` must never have
been reached.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from claimguard.cli.judge import EXIT_FAILED, EXIT_NOT_CONFIGURED, EXIT_OK
from claimguard.cli.judge import run as judge_run
from claimguard.cli.main import build_parser
from claimguard.edu.judge.config import ENV_API_KEY, ENV_BASE_URL, ENV_MODEL, ENV_TIMEOUT
from claimguard.edu.judge.models import JudgeStatus
from claimguard.edu.judge.provider import JevJudge, JudgeHTTPError
from claimguard.edu.judge.sidecar import read_assessments

from tests.judge import (
    API_KEY,
    BASE_URL,
    MODEL,
    FakeTransport,
    assess_args,
    failing,
    forbid_network,
    models_body,
    probe_args,
    sample,
    settings,
    systemone_body,
    write_inputs,
)


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment with no judge configuration at all."""
    for name in (ENV_API_KEY, ENV_BASE_URL, ENV_MODEL, ENV_TIMEOUT):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """An environment that looks like a working judge deployment."""
    monkeypatch.setenv(ENV_API_KEY, API_KEY)
    monkeypatch.setenv(ENV_BASE_URL, BASE_URL)
    monkeypatch.setenv(ENV_MODEL, MODEL)


@pytest.fixture
def inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A results file, a claims file and a sidecar destination."""
    results, claims = write_inputs(tmp_path, [sample(), failing()])
    return results, claims, tmp_path / "judge.jsonl"


def test_the_parser_exposes_probe_and_assess() -> None:
    probe = build_parser().parse_args(["judge", "probe"])
    assert (probe.command, probe.action) == ("judge", "probe")
    assess = build_parser().parse_args(
        ["judge", "assess", "--results", "r.jsonl", "--claims", "c.jsonl", "--output", "o.jsonl"]
    )
    assert assess.action == "assess"
    assert (assess.results, assess.claims, assess.output) == ("r.jsonl", "c.jsonl", "o.jsonl")
    assert assess.rules_dir is None


def test_probe_without_a_key_refuses_and_sends_nothing(
    offline: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    network = forbid_network(monkeypatch)
    assert judge_run(probe_args()) == EXIT_NOT_CONFIGURED
    captured = capsys.readouterr()
    assert "api_key=unset" in captured.out
    assert "no API key configured" in captured.err
    assert network == []


def test_assess_without_a_key_writes_skipped_assessments_offline(
    offline: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    inputs: tuple[Path, Path, Path],
) -> None:
    results, claims, output = inputs
    before = results.read_bytes()
    network = forbid_network(monkeypatch)

    assert judge_run(assess_args(results, claims, output)) == EXIT_NOT_CONFIGURED

    assessments = read_assessments(output)
    assert [entry.status for entry in assessments] == [
        JudgeStatus.SKIPPED,
        JudgeStatus.SKIPPED,
    ]
    assert {entry.provider for entry in assessments} == {"null"}
    assert all("no API key" in entry.reason for entry in assessments)
    assert results.read_bytes() == before, "the graded records are byte-identical"
    captured = capsys.readouterr()
    assert "records=2 assessed=0 skipped=2 failed=0" in captured.out
    assert "no request was made" in captured.err
    assert network == []


def test_assess_with_a_fake_transport_records_a_full_assessment(
    configured: None,
    capsys: pytest.CaptureFixture[str],
    inputs: tuple[Path, Path, Path],
) -> None:
    results, claims, output = inputs
    before = results.read_bytes()
    transport = FakeTransport(body=systemone_body(grounded=0.97, choice="agree", score=2.0))
    provider = JevJudge(settings(), transport=transport)

    assert judge_run(assess_args(results, claims, output), provider=provider) == EXIT_OK

    assessments = read_assessments(output)
    assert [entry.status for entry in assessments] == [
        JudgeStatus.ASSESSED,
        JudgeStatus.ASSESSED,
    ]
    first = assessments[0]
    assert first.model == MODEL
    assert first.advisory.grounded_probability == 0.97
    assert first.advisory.attention_level is not None
    assert first.advisory.attention_level.value == "needs attention today"
    assert results.read_bytes() == before, "judging never rewrites the graded records"
    assert len(transport.requests) == 2
    captured = capsys.readouterr()
    assert "records=2 assessed=2 skipped=0 failed=0" in captured.out
    assert f"input={512 * 2}" in captured.out


def test_assess_reports_a_judge_failure_with_its_own_exit_code(
    configured: None, capsys: pytest.CaptureFixture[str], inputs: tuple[Path, Path, Path]
) -> None:
    results, claims, output = inputs
    provider = JevJudge(settings(), transport=FakeTransport(error=JudgeHTTPError(500, "boom")))

    assert judge_run(assess_args(results, claims, output), provider=provider) == EXIT_FAILED

    assessments = read_assessments(output)
    assert [entry.status for entry in assessments] == [JudgeStatus.FAILED, JudgeStatus.FAILED]
    assert all("HTTP 500" in entry.reason for entry in assessments)
    assert "failed" in capsys.readouterr().err


def test_probe_with_a_fake_transport_lists_the_offered_models(
    configured: None, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = JevJudge(settings(), transport=FakeTransport(body=models_body(("jev-test-1",))))
    assert judge_run(probe_args(), provider=provider) == EXIT_OK
    captured = capsys.readouterr()
    assert "1 model(s) offered" in captured.out
    assert "jev-test-1" in captured.out
    assert "<- configured" in captured.out


def test_probe_flags_a_model_the_credential_does_not_offer(
    configured: None, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = JevJudge(settings(), transport=FakeTransport(body=models_body(("jev-2026-09",))))
    assert judge_run(probe_args(), provider=provider) == EXIT_OK
    assert "is not offered by this credential" in capsys.readouterr().err


def test_a_results_file_that_is_not_the_contract_is_refused(
    offline: None,
    capsys: pytest.CaptureFixture[str],
    inputs: tuple[Path, Path, Path],
) -> None:
    results, claims, output = inputs
    merged: dict[str, Any] = json.loads(results.read_text(encoding="utf-8").splitlines()[0])
    merged["advisory"] = {"grounded_probability": 0.9}
    results.write_text(f"{json.dumps(merged)}\n", encoding="utf-8")

    assert judge_run(assess_args(results, claims, output)) == EXIT_NOT_CONFIGURED
    assert "cannot read --results" in capsys.readouterr().err
    assert not output.exists(), "a refused run writes no sidecar"


def test_the_sidecar_is_rewritten_not_appended_on_a_second_run(
    offline: None, inputs: tuple[Path, Path, Path]
) -> None:
    results, claims, output = inputs
    judge_run(assess_args(results, claims, output))
    judge_run(assess_args(results, claims, output))
    assert len(read_assessments(output)) == 2


def test_an_unknown_action_is_not_silently_accepted() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["judge"])

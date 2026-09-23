"""``claimguard judge`` — the advisory second opinion, probed or run.

Two actions, no hidden ones:

*   ``probe`` — verify that the TypeSafe credential works and discover which
    model names the account can actually use (``GET /v1/models``). This is the
    one command to run the moment the key arrives, before trusting a model name.
*   ``assess`` — judge validated result records and write the advisory sidecar
    (``--results`` + ``--claims`` in, ``--output`` sidecar out).

The judge is advisory only. This command writes one sidecar file and never
touches the records it was given: they are validated against the frozen 15-key
contract, read, and passed to the provider unchanged.

Exit codes distinguish the three states an operator cares about: ``0`` the judge
ran, ``1`` the judge was configured and failed, ``2`` a prerequisite is missing —
most often that no API key is configured, in which case nothing is sent anywhere
and every assessment is ``skipped``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final, cast

from claimguard.cli.tooling import EXIT_REFUSED, refuse
from claimguard.edu.emit import ContractError, validate_record
from claimguard.edu.envelope import Result, load_jsonl
from claimguard.edu.judge.config import JudgeSettings
from claimguard.edu.judge.models import JudgeAssessment
from claimguard.edu.judge.provider import JevJudge, JudgeError, JudgeProvider, build_provider
from claimguard.edu.judge.run import (
    assess_records,
    load_claim_envelopes,
    load_rule_manifest,
    usage_of,
)
from claimguard.edu.judge.sidecar import summarize, write_assessments
from claimguard.edu.policy import RuleDirError
from claimguard.review.app import resolve_rules_dir

EXIT_OK: Final = 0
EXIT_FAILED: Final = 1

#: ``2`` — a prerequisite is missing: no API key, no rule catalogue, a bad input file.
#: Shared with the other commands' ``EXIT_REFUSED`` so "never passed" means one thing.
EXIT_NOT_CONFIGURED: Final = EXIT_REFUSED

#: The provider name that means "nothing was sent" (see :class:`NullJudge`).
NULL_PROVIDER: Final = "null"


def run(args: argparse.Namespace, *, provider: JudgeProvider | None = None) -> int:
    """Dispatch ``judge probe`` or ``judge assess`` (``provider`` is a test seam)."""
    settings = JudgeSettings.from_env()
    if cast(str, args.action) == "probe":
        return _probe(settings, provider)
    return _assess(args, settings, provider)


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------


def _probe(settings: JudgeSettings, provider: JudgeProvider | None) -> int:
    """Verify access and list the models this credential can use."""
    print(f"claimguard judge: {settings.describe()}")
    if not settings.configured() and provider is None:
        print(
            "claimguard judge: no API key configured (CLAIMGUARD_TYPESAFE_API_KEY), so "
            "nothing was sent. Set the key and run `claimguard judge probe` to verify "
            "access and learn which model names exist.",
            file=sys.stderr,
        )
        return EXIT_NOT_CONFIGURED
    judge: JudgeProvider = provider if provider is not None else JevJudge(settings)
    if not isinstance(judge, JevJudge):
        print(
            "claimguard judge: this provider cannot probe (it offers no model list)",
            file=sys.stderr,
        )
        return EXIT_NOT_CONFIGURED
    try:
        report = judge.probe()
    except JudgeError as exc:
        print(f"claimguard judge: probe failed: {exc}", file=sys.stderr)
        return EXIT_FAILED
    print(f"claimguard judge: {report.url} reachable; {len(report.models)} model(s) offered")
    for model in report.models:
        marker = " <- configured" if model.name == report.configured_model else ""
        released = f" ({model.release_date})" if model.release_date else ""
        print(f"  {model.name}{released}: {model.description}{marker}")
    if report.models and not report.configured_model_offered:
        print(
            f"claimguard judge: {report.configured_model!r} is not offered by this credential; "
            f"set CLAIMGUARD_JEV_MODEL to one of: {', '.join(report.names())}",
            file=sys.stderr,
        )
    return EXIT_OK


# ---------------------------------------------------------------------------
# assess
# ---------------------------------------------------------------------------


def _assess(
    args: argparse.Namespace, settings: JudgeSettings, provider: JudgeProvider | None
) -> int:
    """Judge the given records and write the advisory sidecar."""
    results_path = Path(cast(str, args.results))
    claims_path = Path(cast(str, args.claims))
    output_path = Path(cast(str, args.output))

    try:
        records = _load_records(results_path)
    except (OSError, ValueError, ContractError) as exc:
        return refuse(f"cannot read --results: {exc}")
    try:
        claims = load_claim_envelopes(claims_path)
    except (OSError, ValueError) as exc:
        return refuse(f"cannot read --claims: {exc}")
    try:
        rules_dir = Path(cast(str, args.rules_dir)) if args.rules_dir else resolve_rules_dir()
        rules = load_rule_manifest(rules_dir)
    except (RuleDirError, OSError, ValueError) as exc:
        return refuse(f"cannot load the rule catalogue: {exc}")

    judge: JudgeProvider = provider if provider is not None else build_provider(settings)
    assessments = assess_records(records, rules=rules, claims=claims, provider=judge)
    write_assessments(output_path, assessments)
    return _report(settings, judge, assessments, output_path)


def _load_records(path: Path) -> list[Result]:
    """Load and validate the result records the judge is allowed to see.

    Only a record that passes the frozen contract reaches a provider: judging is
    never done on a half-written or contaminated record.
    """
    raw = load_jsonl(path)
    for number, record in enumerate(raw, start=1):
        try:
            validate_record(record)
        except ContractError as exc:
            raise ContractError(f"{path}:{number}: {exc}") from exc
    return raw


def _report(
    settings: JudgeSettings,
    provider: JudgeProvider,
    assessments: Sequence[JudgeAssessment],
    output_path: Path,
) -> int:
    """Print the run summary and return the exit code the run deserves."""
    counts = summarize(assessments)
    print(f"claimguard judge: {settings.describe()}")
    print(f"claimguard judge: provider={provider.name} sidecar={output_path}")
    print(
        f"claimguard judge: records={counts['total']} assessed={counts['assessed']} "
        f"skipped={counts['skipped']} failed={counts['failed']}"
    )
    if provider.name == NULL_PROVIDER:
        print(
            "claimguard judge: the judge is not configured (CLAIMGUARD_TYPESAFE_API_KEY is "
            "unset): no request was made and every assessment is recorded as skipped. The "
            "sidecar is still written, so the shape of a run stays reviewable offline.",
            file=sys.stderr,
        )
        return EXIT_NOT_CONFIGURED
    usage = usage_of(assessments)
    if usage is not None:
        print(
            f"claimguard judge: tokens input={usage.input_tokens} "
            f"output={usage.output_tokens} (output tokens are free)"
        )
    if counts["failed"]:
        print(
            f"claimguard judge: {counts['failed']} assessment(s) failed; every failure is "
            "inert and no result record was changed",
            file=sys.stderr,
        )
        return EXIT_FAILED
    return EXIT_OK

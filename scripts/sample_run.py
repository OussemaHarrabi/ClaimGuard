"""Reproducible end-to-end sample run (the pack checklist's "auditable sample run").

One command, no network, two halves::

    uv run python scripts/sample_run.py

**The demo claim.** One claim from the pack's development split that the
deterministic engine marks FAIL is pushed through the reviewer API *in process*
(an ASGI ``TestClient``: the real routes, the real store, the real schema — no
server, no socket, no outbound network): submit, read the 15 records, read the
failing check's evidence back out of the *original* envelope, find it in the
review queue, record one reviewer decision, then read the append-only audit
ledger for that run.

**The split verdict.** The same engine scores the whole development split through
the frozen CLI (``python -m claimguard.edu.run``) and the *mentor's own* strict
scorer (``<pack>/src/evaluate.py``) grades it, so the transcript shows the
accuracy claim next to the demo claim instead of asking anyone to take a number
on trust.

What it needs, and refuses without (exit code 2, with the fixing command in the
message): a reachable PostgreSQL with the review schema applied, a resolvable
rule catalogue, and the read-only mentor pack. Everything else is local.

What it does NOT prove is printed at the end of every transcript, and stated in
``docs/verification/REPRODUCIBLE-SAMPLE-RUN.md``: the data is synthetic, the 15
checks are an instructional oracle rather than clinical or reimbursement ground
truth, and no claim is ever submitted to a payer.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import httpx
from claimguard.edu.envelope import load_jsonl
from claimguard.edu.policy import RuleDirError
from claimguard.review import audit_events
from claimguard.review.app import create_app, resolve_rules_dir
from claimguard.review.store import ReviewStore, build_engine, resolve_dsn
from fastapi import FastAPI
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from edu_conformance import (  # noqa: E402  (sibling module; sys.path fixed above)
    ConformanceError,
    find_pack_root,
    run_scorer,
)

#: The split the sample run demonstrates. Development is the pack's open split.
DEFAULT_SPLIT = "development"

#: The claim the demo uses by default: two gold-labelled defects (R003 coverage
#: lapse, R004 member/patient mismatch), 13 PASS, no NOT_APPLICABLE noise and no
#: UNABLE_TO_ASSESS — a small, readable, genuinely defective claim.
#: ``tests/sample_run`` re-derives this claim from the split on every test run and
#: asserts it still fails, so the constant cannot rot into a happy path unnoticed.
DEFAULT_CLAIM_ID = "CG-785C09BD9CC8"

#: The reviewer decision the demo records, on the first failing rule.
DEMO_ACTOR = "demo-reviewer"
DEMO_ACTION = "confirm_issue"
DEMO_REASON = (
    "Coverage ended before the service date; checked the source record and confirmed the issue."
)

#: Where the split's predictions and the scorer's metrics are written.
DEFAULT_WORKDIR = Path("artifacts/sample-run")

#: Seconds allowed for the mentor's scorer subprocess.
SCORER_TIMEOUT = 900.0

EXIT_OK = 0
EXIT_REFUSED = 2

#: The honesty block printed with every transcript (pack docs/07 and docs/10).
WHAT_THIS_DOES_NOT_PROVE: tuple[str, ...] = (
    "The data is synthetic teaching data. Every claim, service code, diagnosis code, "
    "provider, policy and payer here is invented for the exercise. Nothing was submitted "
    "to a payer, and this system has no payer-submission path at all.",
    "The 15 checks are an instructional oracle, not clinical or reimbursement ground truth. "
    'PASS means "this fictional rulebook raises no objection" — it is never approval, '
    "authorisation to pay, or a prediction that a payer will pay.",
    "The accuracy number above is agreement with the pack's own gold labels on the supplied "
    "development split (400 claims). It is not accuracy on real claims. The mentor's 200 "
    "held-out claims are not in this repository and were not used.",
    "NOT_IMPLEMENTED counts as incorrect in the mentor's scorer, so the number cannot be "
    "inflated by abstaining from a rule.",
    "A recorded decision is a reviewer's note about one check. It approves nothing, and it "
    "does not overwrite the evidence the check cited.",
    "The audit ledger is a tamper-evident prototype over the demo rows. Production "
    "immutability, retention and access control are described, not built here.",
)


class SampleRunError(RuntimeError):
    """The sample run cannot be produced (missing database, catalogue, pack or claim)."""


def _emit(text: str = "") -> None:
    """Write one line to stdout (ruff's T20 forbids ``print`` in this tree)."""
    sys.stdout.write(text + "\n")


# ---------------------------------------------------------------------------
# Preflight: the three things the run refuses to guess
# ---------------------------------------------------------------------------


def _redact(dsn: str) -> str:
    """Hide the password in a DSN before it reaches a transcript."""
    scheme, separator, rest = dsn.partition("://")
    if not separator:
        return dsn
    credentials, at, host = rest.partition("@")
    if not at:
        return dsn
    user, colon, _password = credentials.partition(":")
    return f"{scheme}://{user}{':' if colon else ''}***@{host}"


def _open_store() -> tuple[ReviewStore, Engine, str]:
    """Open the review store, or refuse with the command that fixes the problem."""
    dsn = resolve_dsn()
    engine = build_engine(dsn)
    store = ReviewStore(engine)
    try:
        revision = store.schema_revision()
    except SQLAlchemyError as exc:
        detail = str(exc).strip().splitlines()[0]
        raise SampleRunError(
            f"the database is not reachable at {_redact(dsn)}: {detail}\n"
            "  start PostgreSQL:            docker compose up -d db\n"
            "  point the app at it:         CLAIMGUARD_DATABASE_URL="
            "postgresql+psycopg://claimguard:claimguard@localhost:5432/claimguard\n"
            "  (the sample run needs the reviewer API's own schema; it does not create it)"
        ) from exc
    if revision is None:
        raise SampleRunError(
            "the review schema is not applied to "
            f"{_redact(dsn)}: run `uv run alembic upgrade head` first"
        )
    return store, engine, dsn


def _resolve_rules_dir() -> Path:
    """Resolve the rule catalogue, or refuse naming the environment variables."""
    try:
        return resolve_rules_dir()
    except RuleDirError as exc:
        raise SampleRunError(
            f"the rule catalogue is not resolvable: {exc}\n"
            "  point at it with CLAIMGUARD_RULES_DIR=<pack>/rules "
            "or CLAIMGUARD_PACK_ROOT=<pack>"
        ) from exc


def _resolve_pack_root(explicit: str | None) -> Path:
    """Resolve the read-only mentor pack, or refuse naming the search that failed."""
    try:
        return find_pack_root(Path(explicit) if explicit else None)
    except ConformanceError as exc:
        raise SampleRunError(
            f"the mentor pack is not resolvable: {exc}\n"
            "  it is delivered reference material and is not tracked in git; "
            "pass --pack-root or set CLAIMGUARD_PACK_ROOT"
        ) from exc


def _catalogue_digest(rules_dir: Path) -> str:
    """SHA-256 of the ``rules.json`` the run actually used (catalogue identity)."""
    return hashlib.sha256((rules_dir / "rules.json").read_bytes()).hexdigest()


def _load_claims(pack_root: Path, split: str) -> list[dict[str, Any]]:
    """The split's claim envelopes, in file order."""
    path = pack_root / "data" / split / "claims.jsonl"
    if not path.is_file():
        raise SampleRunError(f"the split's claim file is missing: {path}")
    return load_jsonl(path)


def _find_claim(claims: Sequence[Mapping[str, Any]], claim_id: str) -> dict[str, Any]:
    """One envelope by claim id, or refuse listing what the split does contain."""
    for claim in claims:
        if claim.get("claim_id") == claim_id:
            return dict(claim)
    raise SampleRunError(
        f"claim {claim_id!r} is not in this split ({len(claims)} claims); "
        f"first ids: {', '.join(str(c.get('claim_id')) for c in claims[:3])}"
    )


# ---------------------------------------------------------------------------
# The demo claim, through the reviewer API
# ---------------------------------------------------------------------------


def _pointer(envelope: Mapping[str, Any], path: str) -> object:
    """Resolve one JSON pointer against the envelope, with the pack's own semantics.

    ``<pack>/src/engine_core.py:pointer`` is the authority this mirrors (leading
    slash stripped, ``~1``/``~0`` unescaped, a numeric token indexing a list), so
    "the value the finding cites" is resolved exactly the way the mentor's scorer
    resolves it. Raises ``KeyError``/``IndexError``/``ValueError`` when the
    pointer does not resolve at all; the caller reports that instead of hiding it.
    """
    node: object = envelope
    if not path:
        return node
    for token in path.strip("/").split("/"):
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = cast("list[Any]", node)[int(key)]
        elif isinstance(node, Mapping):
            node = node[key]
        else:
            raise KeyError(path)
    return node


def _evidence_read_back(
    envelope: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Re-resolve every evidence pointer against the ORIGINAL envelope.

    This is the check a reviewer performs by hand: the value a finding cites must
    still be the value in the claim that was submitted. A pointer that does not
    resolve, or resolves to something else, is reported rather than hidden.
    """
    rows: list[dict[str, Any]] = []
    for entry in evidence:
        path = str(entry.get("path", ""))
        value = entry.get("value")
        resolved = False
        found: object = None
        try:
            found = _pointer(envelope, path)
            resolved = True
        except (KeyError, IndexError, ValueError):
            resolved = False
        rows.append(
            {
                "path": path,
                "value": value,
                "resolved": resolved,
                "matches": resolved and found == value,
            }
        )
    return rows


async def _record_decision(
    client: httpx.AsyncClient, run_id: str, rule_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Record the demo decision once, and stay re-runnable on the second call.

    The ledger is append-only and the decision state machine refuses a repeated
    terminal action, so a second run of this script reports the decision that is
    already there instead of writing a duplicate row.
    """
    history = (await client.get(f"/v1/runs/{run_id}/decisions")).json()["entries"]
    for entry in history:
        event = entry["decision"]["event"]
        if (
            event["rule_id"] == rule_id
            and event["action"] == DEMO_ACTION
            and event["actor"] == DEMO_ACTOR
        ):
            return {"already_recorded": True, "review": entry["review"], "event": event}, history
    response = await client.post(
        f"/v1/runs/{run_id}/decisions",
        json={
            "rule_id": rule_id,
            "action": DEMO_ACTION,
            "actor": DEMO_ACTOR,
            "reason": DEMO_REASON,
        },
    )
    if response.status_code != 201:
        raise SampleRunError(
            f"recording the decision failed: HTTP {response.status_code} {response.text}"
        )
    body = response.json()
    decision = {
        "already_recorded": False,
        "review": body["review"],
        "event": body["decision"]["event"],
        "decision_id": body["decision"]["decision_id"],
        "audit": body["audit"],
    }
    after = (await client.get(f"/v1/runs/{run_id}/decisions")).json()["entries"]
    return decision, after


def _audit_rows(engine: Engine, run_id: str) -> tuple[list[dict[str, Any]], list[str]]:
    """The run's ledger rows and the event ids whose chain hash does not verify."""
    with engine.connect() as connection:
        rows = audit_events.events_for_ref(connection, run_id)
        broken = audit_events.unlinked_refs(connection, [run_id])
    payload = [
        {
            "event_id": row.event_id,
            "at": row.at.isoformat(),
            "kind": row.kind,
            "decision": row.decision,
            "reason_code": row.reason_code,
            "finding_ids": list(row.finding_ids),
            "rule_version": row.rule_version,
            "model_version": row.model_version,
            "prev_hash": row.prev_hash,
            "chain_hash": row.chain_hash,
        }
        for row in rows
    ]
    return payload, broken.get(run_id, [])


async def _drive_api(
    *,
    app: FastAPI,
    envelope: Mapping[str, Any],
    claim_id: str,
    gold: Mapping[str, str],
) -> dict[str, Any]:
    """Drive the reviewer API in process: submit, read, queue, decide."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://review.test") as client:
        health = await client.get("/v1/health")
        if health.status_code != 200:
            raise SampleRunError(f"GET /v1/health failed: {health.status_code} {health.text}")

        submitted = await client.post("/v1/claims", json={"claim": envelope})
        if submitted.status_code != 201:
            raise SampleRunError(
                f"POST /v1/claims failed: HTTP {submitted.status_code} {submitted.text}"
            )
        run_body = submitted.json()
        run_id = str(run_body["run"]["run_id"])

        fetched = await client.get(f"/v1/runs/{run_id}/results")
        if fetched.status_code != 200:
            raise SampleRunError(
                f"GET /v1/runs/{run_id}/results failed: HTTP {fetched.status_code}"
            )
        results: list[dict[str, Any]] = fetched.json()["results"]
        if len(results) != 15:
            raise SampleRunError(f"the run returned {len(results)} records, not 15")

        failures = [
            {
                "rule_id": record["rule_id"],
                "status": record["status"],
                "severity": record["severity"],
                "explanation": record["explanation"],
                "corrective_action": record["corrective_action"],
                "affected_line_ids": record["affected_line_ids"],
                "requires_human_review": record["requires_human_review"],
                "evidence": _evidence_read_back(envelope, record["evidence"]),
                "gold_status": gold.get(record["rule_id"]),
            }
            for record in results
            if record["status"] == "FAIL"
        ]
        if not failures:
            raise SampleRunError(
                f"claim {claim_id} has no failing check, so the demo would prove nothing; "
                "choose a defective claim with --claim-id"
            )

        queue = (await client.get("/v1/queue", params={"claim_id": claim_id})).json()
        decision, history = await _record_decision(client, run_id, str(failures[0]["rule_id"]))
        health_body = health.json()

    return {
        "claim_id": claim_id,
        "health": health_body,
        "run": run_body["run"],
        "results": run_body["results"],
        "needs_attention": run_body["needs_attention"],
        "by_status": run_body["by_status"],
        "duplicate": run_body["duplicate"],
        "run_audit": run_body["audit"],
        "statuses": {record["rule_id"]: record["status"] for record in results},
        "failures": failures,
        "queue": queue["counts"],
        "queue_claim": next((row for row in queue["claims"] if row["claim_id"] == claim_id), None),
        "decision": decision,
        "decisions": [
            {
                "decision_id": entry["decision"]["decision_id"],
                "review_status": entry["review"]["status"],
                "action": entry["decision"]["event"]["action"],
                "actor": entry["decision"]["event"]["actor"],
                "reason": entry["decision"]["event"]["reason"],
                "original_status": entry["decision"]["event"]["original_status"],
                "at": entry["decision"]["event"]["created_at"],
            }
            for entry in history
        ],
    }


def _demo_claim(
    *,
    store: ReviewStore,
    engine: Engine,
    rules_dir: Path,
    claims: Sequence[Mapping[str, Any]],
    claim_id: str,
    gold: Mapping[str, str],
) -> dict[str, Any]:
    """Submit the demo claim, read its findings back, decide, and read the ledger."""
    envelope = _find_claim(claims, claim_id)
    app = create_app(store=store, rules_dir=rules_dir)
    demo = asyncio.run(_drive_api(app=app, envelope=envelope, claim_id=claim_id, gold=gold))
    ledger, broken = _audit_rows(engine, str(demo["run"]["run_id"]))
    demo["envelope"] = {
        "submission_date": envelope.get("submission_date"),
        "total_amount": envelope.get("total_amount"),
        "currency": envelope.get("currency"),
        "lines": [
            {
                "line_id": line.get("line_id"),
                "service_code": line.get("service_code"),
                "service_date": line.get("service_date"),
                "net_amount": line.get("net_amount"),
            }
            for line in envelope.get("lines", [])
        ],
    }
    demo["audit"] = {"events": ledger, "broken_event_ids": broken}
    return demo


# ---------------------------------------------------------------------------
# The split verdict: the mentor's own scorer
# ---------------------------------------------------------------------------


def _split_verdict(
    *, pack_root: Path, split: str, rules_dir: Path, workdir: Path
) -> dict[str, Any]:
    """Score the whole split with the engine, then grade it with the mentor's oracle."""
    claims_path = pack_root / "data" / split / "claims.jsonl"
    if not claims_path.is_file():
        raise SampleRunError(f"the split's claim file is missing: {claims_path}")
    workdir.mkdir(parents=True, exist_ok=True)
    predictions = workdir / "predictions.jsonl"
    engine_command = [
        sys.executable,
        "-m",
        "claimguard.edu.run",
        "--claims",
        str(claims_path),
        "--rules-dir",
        str(rules_dir),
        "--output",
        str(predictions),
    ]
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell, no external input
        engine_command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise SampleRunError(
            "the engine could not produce predictions for the split "
            f"(exit {completed.returncode}):\n{completed.stderr.strip()}"
        )
    try:
        scorer = run_scorer(
            python=sys.executable,
            pack_root=pack_root,
            split=split,
            pred=predictions,
            metrics_path=workdir / "metrics.json",
            timeout=SCORER_TIMEOUT,
        )
    except ConformanceError as exc:
        raise SampleRunError(f"the mentor's scorer could not be run: {exc}") from exc
    if not scorer.accepted:
        raise SampleRunError(
            f"the mentor's scorer rejected the predictions (exit {scorer.exit_code}):\n"
            f"{scorer.message()}"
        )
    metrics: dict[str, Any] = json.loads(scorer.metrics_path.read_text(encoding="utf-8"))
    return {
        "engine_command": engine_command,
        "engine_stderr": completed.stderr.strip(),
        "scorer_command": list(scorer.command),
        "scorer_exit_code": scorer.exit_code,
        "overall": metrics["overall"],
        "claims_with_all_statuses_correct": metrics["claims_with_all_statuses_correct"],
        "note": metrics["note"],
        "predictions": str(predictions),
        "metrics_path": str(scorer.metrics_path),
    }


# ---------------------------------------------------------------------------
# Payload assembly and rendering
# ---------------------------------------------------------------------------


def run_sample(
    *,
    claim_id: str,
    split: str,
    pack_root_arg: str | None,
    workdir: Path,
) -> dict[str, Any]:
    """Produce the whole sample-run payload, or raise :class:`SampleRunError`."""
    # Resolve the cheap, database-free inputs first: a wrong pack path or an unknown
    # claim must be reported without needing PostgreSQL at all — and opening the store
    # first would leak its connection whenever a later step refused.
    rules_dir = _resolve_rules_dir()
    pack_root = _resolve_pack_root(pack_root_arg)
    claims = _load_claims(pack_root, split)
    gold = _gold_for(pack_root, split, claim_id)

    store, engine, dsn = _open_store()
    try:
        demo = _demo_claim(
            store=store,
            engine=engine,
            rules_dir=rules_dir,
            claims=claims,
            claim_id=claim_id,
            gold=gold,
        )
        verdict = _split_verdict(
            pack_root=pack_root, split=split, rules_dir=rules_dir, workdir=workdir
        )
        revision = store.schema_revision()
    except BaseException:
        # Nothing here owns the engine; a failed run must not leave a pooled
        # connection open behind it.
        engine.dispose()
        raise
    return {
        "split": split,
        "claim_id": claim_id,
        "pack_root": str(pack_root),
        "rules_dir": str(rules_dir),
        "rules_sha256": _catalogue_digest(rules_dir),
        "database": {"dsn": _redact(dsn), "schema_revision": revision},
        "workdir": str(workdir),
        "demo": demo,
        "split_verdict": verdict,
        "does_not_prove": list(WHAT_THIS_DOES_NOT_PROVE),
    }


def _gold_for(pack_root: Path, split: str, claim_id: str) -> dict[str, str]:
    """The mentor's gold statuses for one claim (empty when the split has no labels)."""
    path = pack_root / "data" / split / "expected_results.jsonl"
    if not path.is_file():
        return {}
    return {
        str(record["rule_id"]): str(record["status"])
        for record in load_jsonl(path)
        if record.get("claim_id") == claim_id
    }


def _short(hash_value: str, width: int = 16) -> str:
    """A hash, shortened for a transcript (the full value stays in the JSON payload)."""
    return hash_value[:width] + "…" if len(hash_value) > width else hash_value


def format_transcript(payload: Mapping[str, Any]) -> str:
    """Render the payload as the readable transcript a judge or teammate reads."""
    demo = payload["demo"]
    run = demo["run"]
    verdict = payload["split_verdict"]
    overall = verdict["overall"]
    lines: list[str] = []

    lines.append("ClaimGuard AI — reproducible sample run")
    lines.append("=" * 39)
    lines.append("Synthetic teaching data. No claim is submitted to a payer.")
    lines.append("")
    lines.append(f"split        : {payload['split']}")
    lines.append(f"pack root    : {payload['pack_root']}")
    lines.append(f"rules dir    : {payload['rules_dir']}")
    lines.append(f"rules.json   : sha256 {payload['rules_sha256']}")
    lines.append(
        f"database     : {payload['database']['dsn']} "
        f"(schema revision {payload['database']['schema_revision']})"
    )
    lines.append("network      : none (ASGI app in process; no server, no socket)")
    lines.append("")

    lines.append(f"[1/7] claim under review — {demo['claim_id']}")
    envelope = demo["envelope"]
    lines.append(
        f"      submitted {envelope['submission_date']} | "
        f"{envelope['currency']} {envelope['total_amount']} | "
        f"{len(envelope['lines'])} line(s)"
    )
    for line in envelope["lines"]:
        lines.append(
            f"      line {line['line_id']}: {line['service_code']} on {line['service_date']}"
            f" | net {line['net_amount']}"
        )
    lines.append("")

    lines.append("[2/7] POST /v1/claims -> 201")
    lines.append(f"      run_id       : {run['run_id']}")
    lines.append(f"      version      : {run['version']} (supersedes {run['supersedes_run_id']})")
    lines.append(f"      input_hash   : {run['input_hash']}")
    lines.append(
        f"      versions     : rule {run['rule_version']} | model {run['model_version']}"
        f" | prompt {run['prompt_version']}"
    )
    lines.append(f"      by_status    : {_counts(demo['by_status'])}")
    lines.append(
        f"      needs_attention: {demo['needs_attention']} | duplicate: {demo['duplicate']}"
    )
    lines.append(
        f"      audit        : {demo['run_audit']['kind']} event "
        f"{demo['run_audit']['event_id']} chain_hash {_short(demo['run_audit']['chain_hash'])}"
    )
    lines.append("")

    lines.append("[3/7] GET /v1/runs/{run_id}/results -> 15 records")
    for rule_id, status in demo["statuses"].items():
        lines.append(f"      {rule_id}  {status}")
    lines.append("")

    lines.append("[4/7] failing checks, with evidence read back from the ORIGINAL envelope")
    for failure in demo["failures"]:
        lines.append(
            f"      {failure['rule_id']} {failure['status']} {failure['severity']}"
            f" — {failure['explanation']}"
        )
        lines.append(
            f"        gold label: {failure['gold_status']} | "
            f"affected lines: {failure['affected_line_ids'] or 'none'} | "
            f"requires_human_review: {failure['requires_human_review']}"
        )
        for evidence in failure["evidence"]:
            verdict_text = "resolves" if evidence["matches"] else "MISMATCH"
            lines.append(
                f"        {evidence['path']:<32} = {evidence['value']!r}  [{verdict_text}]"
            )
        lines.append(f"        corrective action: {failure['corrective_action']}")
    lines.append("")

    queue = demo["queue"]
    lines.append(f"[5/7] GET /v1/queue?claim_id={demo['claim_id']} -> counts for this claim")
    lines.append(
        f"      findings={queue['findings']} unresolved={queue['unresolved']} "
        f"resolved={queue['resolved']} by_severity={queue['by_severity']}"
    )
    lines.append(f"      by_review_status={queue['by_review_status']}")
    lines.append("")

    decision = demo["decision"]
    event = decision["event"]
    lines.append("[6/7] POST /v1/runs/{run_id}/decisions")
    lines.append(
        f"      {event['rule_id']} {event['action']} by {event['actor']}"
        f" | original status {event['original_status']}"
    )
    lines.append(f"      reason       : {event['reason']}")
    lines.append(
        f"      review state : {decision['review']['status']} "
        f"(decisions on this finding: {decision['review']['decision_count']})"
        + ("  [already recorded; nothing written]" if decision["already_recorded"] else "")
    )
    lines.append(f"      decisions on this run: {len(demo['decisions'])}")
    lines.append("")

    lines.append("[7/7] audit ledger for this run (append-only, hash-chained)")
    for row in demo["audit"]["events"]:
        lines.append(f"      {row['kind']:<15} {row['event_id']}  decision={row['decision']}")
        lines.append(
            f"        finding_ids={row['finding_ids']} rule_version={row['rule_version']}"
            f" model_version={row['model_version']}"
        )
        if row["reason_code"]:
            lines.append(f"        reason_code={row['reason_code']}")
        lines.append(
            f"        prev_hash={_short(row['prev_hash'])} chain_hash={_short(row['chain_hash'])}"
        )
    broken = demo["audit"]["broken_event_ids"]
    lines.append(
        f"      chain verified: {len(demo['audit']['events'])} event(s) recomputed; "
        f"{len(broken)} unlinked"
    )
    lines.append("")

    lines.append(f"split verdict — the mentor's own strict scorer, over all of {payload['split']}")
    lines.append(f"      engine : {' '.join(verdict['engine_command'])}")
    for stderr_line in verdict["engine_stderr"].splitlines():
        lines.append(f"               {stderr_line}")
    lines.append(f"      scorer : {' '.join(verdict['scorer_command'])}")
    lines.append(f"      scorer exit {verdict['scorer_exit_code']} (0 = predictions accepted)")
    lines.append(
        f"      overall: {overall['count']} claim-rule pairs | "
        f"status_accuracy {_number(overall['status_accuracy'])} | "
        f"issue_precision {_number(overall['issue_precision'])} | "
        f"issue_recall {_number(overall['issue_recall'])} | "
        f"false_alarm_rate {_number(overall['false_alarm_rate'])}"
    )
    lines.append(
        f"      counts : tp={overall['tp']} fp={overall['fp']} fn={overall['fn']} "
        f"tn={overall['tn']} | not_implemented={overall['not_implemented']} "
        f"| false_abstentions={overall['false_abstentions']} "
        f"| missed_abstentions={overall['missed_abstentions']}"
    )
    lines.append(
        f"      claims with all 15 statuses correct: {verdict['claims_with_all_statuses_correct']}"
    )
    lines.append(f"      scorer note: {verdict['note']}")
    lines.append("")

    lines.append("what this sample run does NOT prove")
    for statement in payload["does_not_prove"]:
        lines.append(f"  - {statement}")
    lines.append("")
    lines.append(f"artifacts: {payload['workdir']} (predictions.jsonl, metrics.json)")
    return "\n".join(lines)


def _counts(counts: Mapping[str, Any]) -> str:
    """Render a status→count mapping in the pack's status order."""
    order = ("PASS", "FAIL", "UNABLE_TO_ASSESS", "NOT_APPLICABLE", "NOT_IMPLEMENTED")
    return " ".join(f"{name}={counts.get(name, 0)}" for name in order)


def _number(value: Any) -> str:
    """Four decimals, or ``null`` — never a fabricated 100% for an undefined metric."""
    return "null" if value is None else f"{float(value):.4f}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reproducible end-to-end sample run: one defective development-split claim "
            "through the reviewer API, plus the mentor's scorer verdict on the whole split."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--claim-id",
        default=DEFAULT_CLAIM_ID,
        help="claim to demonstrate; must exist in the split and fail at least one check",
    )
    parser.add_argument("--split", default=DEFAULT_SPLIT, help="pack split to use")
    parser.add_argument(
        "--pack-root", default=None, help="mentor pack root (default: auto-discover)"
    )
    parser.add_argument(
        "--workdir",
        default=str(DEFAULT_WORKDIR),
        help="where the split's predictions.jsonl and metrics.json are written",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the whole payload as JSON instead"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the sample and print the transcript; return a process exit code."""
    args = parse_args(argv)
    try:
        payload = run_sample(
            claim_id=str(args.claim_id),
            split=str(args.split),
            pack_root_arg=args.pack_root,
            workdir=Path(args.workdir),
        )
    except SampleRunError as exc:
        _emit(f"sample run refused: {exc}")
        return EXIT_REFUSED
    if args.json:
        _emit(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        _emit(format_transcript(payload))
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())

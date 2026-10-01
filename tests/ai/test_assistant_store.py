"""Integration tests: the assistant's conversation store (migration 0011).

**These tests need PostgreSQL** (skipped automatically when it is unreachable; see
``tests/review/conftest.py``). They run against the real schema — the same tables production
uses — because the invariants under test are database invariants: a conversation is unique per
reviewer, a turn cannot be rewritten, and a ``seq`` cannot be assigned twice.

Every test removes the run it created (the ``findings`` fixture), and the run's conversation
goes with it through ``ON DELETE CASCADE``, so the database is left as it was found.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Final

import pytest
from claimguard.ai.schemas import AssistantThreadRef, AssistantTurn
from claimguard.ai.store import (
    AssistantStore,
    AssistantStoreError,
    ThreadClosed,
    ThreadNotFound,
    UnknownFinding,
    UnknownRun,
)
from claimguard.review.store import RESULTS, RUNS, build_engine
from sqlalchemy import Engine, delete, func, insert, text
from sqlalchemy.exc import DBAPIError

from tests.review.conftest import TEST_DSN, requires_db

pytestmark = [pytest.mark.integration, requires_db]

#: The tenant migration 0005 seeds, so a run can be inserted without creating a clinic first.
TENANT: Final = "clinic-legacy-demo"

#: A tenant that owns nothing here: every statement made with it must come back empty-handed.
OTHER_TENANT: Final = "clinic-not-ours"

#: The finding the conversation is about, and a second one on the same run so the tests can show
#: that one run holds one thread per finding.
RULE: Final = "R003"
OTHER_RULE: Final = "R004"
FINDINGS: Final[tuple[tuple[int, str], ...]] = ((3, RULE), (4, OTHER_RULE))

#: A rule id the run above does NOT have: shape-valid, so the store refuses it on the finding
#: and not on the format.
MISSING_RULE: Final = "R009"

ACTOR: Final = "rev-assistant-1"
OTHER_ACTOR: Final = "rev-assistant-2"

RULE_VERSION: Final = "rules/1.0.0"
MODEL_VERSION: Final = "qwen/qwen3.8-27b"
PROMPT_VERSION: Final = "assistant/1"
RECEIPT: Final = hashlib.sha256(b"assistant-store-test-turn").hexdigest()
LATENCY_MS: Final = 812

#: How many reviewers ask at once in the concurrency test. Well under the engine's pool of
#: 5 + 10, so every append really is a simultaneous connection rather than a queue.
CONCURRENT_TURNS: Final = 8

#: The pack's five keys — the shape the graded explanation layer and every assistant answer share.
ANSWER: Final[dict[str, Any]] = {
    "explanation": (
        "Coverage ended on 2026-03-09 while the service date was 2026-03-10, so the claim "
        "falls outside the covered period."
    ),
    "correction_recommendation": (
        "Confirm the coverage end date against the payer's eligibility response, then correct "
        "the coverage dates or attach proof of continued coverage."
    ),
    "cited_evidence_paths": ["coverage.end_date"],
    "cited_rule_ids": [RULE],
    "needs_human_review": True,
}

#: A reviewer's turn: a question and the verification of the turn that follows it. The store
#: records the verification it is handed and does not police that pairing — which turn carries
#: which value is the graph's contract, not a database one.
REVIEWER_TURN: Final[dict[str, Any]] = {
    "role": "reviewer",
    "question": "Why is this claim flagged?",
    "answer": None,
    "verification": "accepted",
    "reasons": [],
    "model_version": "none",
    "prompt_version": "none",
    "receipt": None,
    "latency_ms": None,
}

ASSISTANT_TURN: Final[dict[str, Any]] = {
    "role": "assistant",
    "question": None,
    "answer": ANSWER,
    "verification": "accepted",
    "reasons": [],
    "model_version": MODEL_VERSION,
    "prompt_version": PROMPT_VERSION,
    "receipt": RECEIPT,
    "latency_ms": LATENCY_MS,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """A UTC-pinned engine for the test DSN (the same one the review tests build)."""
    created = build_engine(TEST_DSN)
    yield created
    created.dispose()


@pytest.fixture
def store(engine: Engine) -> AssistantStore:
    """The assistant store over the migrated database."""
    return AssistantStore(engine)


class Findings:
    """Creates the runs the assistant tests talk about, and removes them afterwards."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._run_ids: list[str] = []

    def open(self, *, claim_id: str | None = None) -> tuple[str, str]:
        """Store one run of one claim, with its two findings; return ``(run_id, claim_id)``."""
        run_id = f"RUN-{uuid.uuid4().hex}"
        claim = claim_id if claim_id is not None else f"CG-ASSIST-{uuid.uuid4().hex[:10]}"
        with self._engine.begin() as connection:
            connection.execute(
                insert(RUNS).values(
                    run_id=run_id,
                    tenant_id=TENANT,
                    claim_id=claim,
                    version=1,
                    input_hash=hashlib.sha256(run_id.encode("utf-8")).hexdigest(),
                    envelope={"claim_id": claim},
                    trace_id=uuid.uuid4().hex,
                    rule_version=RULE_VERSION,
                    model_version="deterministic-engine/1.0.0",
                    prompt_version="none",
                    initiated_by=ACTOR,
                    created_at=func.now(),
                )
            )
            connection.execute(
                insert(RESULTS),
                [
                    {
                        "run_id": run_id,
                        "tenant_id": TENANT,
                        "claim_id": claim,
                        "seq": seq,
                        "rule_id": rule_id,
                        "rule_version": RULE_VERSION,
                        "status": "FAIL",
                        "severity": "high",
                        "affected_line_ids": ["L1"],
                        "evidence": [{"path": "coverage.end_date", "value": "2026-03-09"}],
                        "rule_source": "Coverage must be active on the service date.",
                        "explanation": "Coverage ended before the service date.",
                        "corrective_action": "Correct the coverage dates.",
                        "confidence": None,
                        "confidence_kind": "not_probabilistic",
                        "requires_human_review": True,
                        "method": "deterministic",
                        "review_status": "unreviewed",
                        "created_at": func.now(),
                    }
                    for seq, rule_id in FINDINGS
                ],
            )
        self._run_ids.append(run_id)
        return run_id, claim

    def new_thread(self, store: AssistantStore, *, actor: str = ACTOR) -> AssistantThreadRef:
        """Store a run and open ``actor``'s conversation about its ``R003`` finding."""
        run_id, claim_id = self.open()
        return store.open_thread(
            tenant_id=TENANT,
            run_id=run_id,
            claim_id=claim_id,
            rule_id=RULE,
            actor=actor,
        )

    def purge(self) -> None:
        """Delete every run this test created; conversations and turns cascade away."""
        if not self._run_ids:
            return
        with self._engine.begin() as connection:
            for run_id in self._run_ids:
                connection.execute(delete(RUNS).where(RUNS.c.run_id == run_id))


@pytest.fixture
def findings(engine: Engine) -> Iterator[Findings]:
    """Per-test run factory whose rows are removed at teardown."""
    box = Findings(engine)
    yield box
    box.purge()


def append(
    store: AssistantStore, thread_id: str, tenant_id: str = TENANT, **overrides: Any
) -> AssistantTurn:
    """Append one reviewer turn, with any field overridden."""
    values: dict[str, Any] = {**REVIEWER_TURN, **overrides}
    return store.append_turn(thread_id, tenant_id=tenant_id, **values)


# ---------------------------------------------------------------------------
# Threads
# ---------------------------------------------------------------------------


def test_opening_a_thread_twice_resumes_it_and_each_reviewer_gets_their_own(
    store: AssistantStore, findings: Findings
) -> None:
    run_id, claim_id = findings.open()
    first = store.open_thread(
        tenant_id=TENANT, run_id=run_id, claim_id=claim_id, rule_id=RULE, actor=ACTOR
    )
    again = store.open_thread(
        tenant_id=TENANT, run_id=run_id, claim_id=claim_id, rule_id=RULE, actor=ACTOR
    )

    assert first.thread_id == again.thread_id
    assert again.created_at == first.created_at
    assert again.closed_at is None
    assert (first.tenant_id, first.run_id, first.claim_id, first.rule_id, first.created_by) == (
        TENANT,
        run_id,
        claim_id,
        RULE,
        ACTOR,
    )

    assert store.find_thread(tenant_id=TENANT, run_id=run_id, rule_id=RULE, actor=ACTOR) == first
    assert store.find_thread(tenant_id=TENANT, run_id=run_id, rule_id=RULE, actor=OTHER_ACTOR) is (
        None
    )
    assert store.require_thread(first.thread_id, tenant_id=TENANT) == first

    colleague = store.open_thread(
        tenant_id=TENANT, run_id=run_id, claim_id=claim_id, rule_id=RULE, actor=OTHER_ACTOR
    )
    other_finding = store.open_thread(
        tenant_id=TENANT, run_id=run_id, claim_id=claim_id, rule_id=OTHER_RULE, actor=ACTOR
    )
    assert len({first.thread_id, colleague.thread_id, other_finding.thread_id}) == 3
    assert colleague.created_by == OTHER_ACTOR
    assert other_finding.rule_id == OTHER_RULE
    assert store.find_thread(tenant_id=TENANT, run_id=run_id, rule_id=OTHER_RULE, actor=ACTOR) == (
        other_finding
    )


def test_a_thread_is_invisible_to_another_tenant(store: AssistantStore, findings: Findings) -> None:
    run_id, claim_id = findings.open()
    thread = store.open_thread(
        tenant_id=TENANT, run_id=run_id, claim_id=claim_id, rule_id=RULE, actor=ACTOR
    )
    stored = append(store, thread.thread_id, **ASSISTANT_TURN)

    with pytest.raises(ThreadNotFound):
        store.require_thread(thread.thread_id, tenant_id=OTHER_TENANT)
    with pytest.raises(ThreadNotFound):
        store.conversation(thread.thread_id, tenant_id=OTHER_TENANT)
    with pytest.raises(ThreadNotFound):
        store.turn_count(thread.thread_id, tenant_id=OTHER_TENANT)
    with pytest.raises(ThreadNotFound):
        store.close_thread(thread.thread_id, tenant_id=OTHER_TENANT)
    with pytest.raises(ThreadNotFound):
        append(store, thread.thread_id, OTHER_TENANT, **REVIEWER_TURN)
    assert (
        store.find_thread(tenant_id=OTHER_TENANT, run_id=run_id, rule_id=RULE, actor=ACTOR) is None
    )

    # None of that touched the owner's conversation.
    assert store.conversation(thread.thread_id, tenant_id=TENANT).turns == [stored]
    assert store.turn_count(thread.thread_id, tenant_id=TENANT) == 1


def test_a_closed_thread_refuses_further_turns(store: AssistantStore, findings: Findings) -> None:
    run_id, claim_id = findings.open()
    thread = store.open_thread(
        tenant_id=TENANT, run_id=run_id, claim_id=claim_id, rule_id=RULE, actor=ACTOR
    )
    append(store, thread.thread_id)

    closed = store.close_thread(thread.thread_id, tenant_id=TENANT)
    assert closed.closed_at is not None
    assert store.close_thread(thread.thread_id, tenant_id=TENANT).closed_at == closed.closed_at
    assert store.require_thread(thread.thread_id, tenant_id=TENANT).closed_at == closed.closed_at

    with pytest.raises(ThreadClosed):
        append(store, thread.thread_id, question="One more question?")
    assert store.turn_count(thread.thread_id, tenant_id=TENANT) == 1

    # Re-opening the finding returns the closed conversation as it is instead of clearing it.
    reopened = store.open_thread(
        tenant_id=TENANT, run_id=run_id, claim_id=claim_id, rule_id=RULE, actor=ACTOR
    )
    assert reopened.thread_id == thread.thread_id
    assert reopened.closed_at == closed.closed_at


# ---------------------------------------------------------------------------
# Turns
# ---------------------------------------------------------------------------


def test_turns_are_returned_in_order_and_numbered_from_one(
    store: AssistantStore, findings: Findings
) -> None:
    thread = findings.new_thread(store)
    asked = append(store, thread.thread_id, question="Why is this claim flagged?")
    answered = append(store, thread.thread_id, **ASSISTANT_TURN)
    refused = append(
        store,
        thread.thread_id,
        role="assistant",
        answer=None,
        verification="refused",
        reasons=["the question asks about a different claim", "no evidence path covers it"],
        model_version=MODEL_VERSION,
        prompt_version=PROMPT_VERSION,
    )
    followed = append(store, thread.thread_id, question="And what do I attach?")

    assert [asked.sequence, answered.sequence, refused.sequence, followed.sequence] == [1, 2, 3, 4]
    assert len({turn.turn_id for turn in (asked, answered, refused, followed)}) == 4
    assert [turn.thread_id for turn in (asked, answered, refused, followed)] == [
        thread.thread_id
    ] * 4

    assert asked.role == "reviewer"
    assert asked.question == "Why is this claim flagged?"
    assert asked.answer is None
    assert answered.role == "assistant"
    assert answered.answer == ANSWER, "the five keys must survive the JSONB round trip unchanged"
    assert answered.receipt == RECEIPT
    assert answered.latency_ms == LATENCY_MS
    assert answered.model_version == MODEL_VERSION
    assert answered.prompt_version == PROMPT_VERSION
    assert refused.verification == "refused"
    assert refused.answer is None
    assert refused.reasons == [
        "the question asks about a different claim",
        "no evidence path covers it",
    ]

    conversation = store.conversation(thread.thread_id, tenant_id=TENANT)
    assert conversation.thread == thread
    assert conversation.turns == [asked, answered, refused, followed]
    assert [turn.sequence for turn in conversation.turns] == [1, 2, 3, 4]
    assert store.turn_count(thread.thread_id, tenant_id=TENANT) == 4


def test_a_stored_turn_cannot_be_updated(
    store: AssistantStore, findings: Findings, engine: Engine
) -> None:
    """The immutability guarantee is the database's, not the store's good manners."""
    thread = findings.new_thread(store)
    stored = append(store, thread.thread_id, question="Why is this claim flagged?")

    with pytest.raises(DBAPIError) as refusal, engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE claimguard.assistant_turns SET question = 'rewritten' "
                "WHERE turn_id = :turn_id"
            ),
            {"turn_id": uuid.UUID(stored.turn_id)},
        )
    assert "immutable" in str(refusal.value)

    served = store.conversation(thread.thread_id, tenant_id=TENANT).turns
    assert [turn.question for turn in served] == ["Why is this claim flagged?"]


def test_simultaneous_appends_get_distinct_sequences(
    store: AssistantStore, findings: Findings
) -> None:
    """``seq`` is allocated under the thread's row lock, not left to a unique violation."""
    thread = findings.new_thread(store)

    def ask(index: int) -> int:
        return append(store, thread.thread_id, question=f"question {index}").sequence

    with ThreadPoolExecutor(max_workers=CONCURRENT_TURNS) as pool:
        sequences = list(pool.map(ask, range(CONCURRENT_TURNS)))

    assert sorted(sequences) == list(range(1, CONCURRENT_TURNS + 1))
    assert store.turn_count(thread.thread_id, tenant_id=TENANT) == CONCURRENT_TURNS
    stored = store.conversation(thread.thread_id, tenant_id=TENANT).turns
    assert [turn.sequence for turn in stored] == list(range(1, CONCURRENT_TURNS + 1))


def test_a_turn_outside_the_documented_values_is_refused_before_it_is_written(
    store: AssistantStore, findings: Findings
) -> None:
    thread = findings.new_thread(store)

    with pytest.raises(AssistantStoreError):
        append(store, thread.thread_id, role="system")
    with pytest.raises(AssistantStoreError):
        append(store, thread.thread_id, verification="probably")
    with pytest.raises(AssistantStoreError):
        append(store, thread.thread_id, model_version="   ")

    assert store.turn_count(thread.thread_id, tenant_id=TENANT) == 0


# ---------------------------------------------------------------------------
# Unknown runs, findings and threads
# ---------------------------------------------------------------------------


def test_opening_a_thread_about_a_finding_the_run_does_not_have_is_refused(
    store: AssistantStore, findings: Findings
) -> None:
    run_id, claim_id = findings.open()

    with pytest.raises(UnknownRun):
        store.open_thread(
            tenant_id=TENANT,
            run_id=f"RUN-{uuid.uuid4().hex}",
            claim_id=claim_id,
            rule_id=RULE,
            actor=ACTOR,
        )
    with pytest.raises(UnknownRun):
        store.open_thread(
            tenant_id=OTHER_TENANT, run_id=run_id, claim_id=claim_id, rule_id=RULE, actor=ACTOR
        )
    with pytest.raises(UnknownRun):
        store.open_thread(
            tenant_id=TENANT,
            run_id=run_id,
            claim_id="CG-SOMEONE-ELSES-CLAIM",
            rule_id=RULE,
            actor=ACTOR,
        )
    with pytest.raises(UnknownFinding):
        store.open_thread(
            tenant_id=TENANT,
            run_id=run_id,
            claim_id=claim_id,
            rule_id=MISSING_RULE,
            actor=ACTOR,
        )

    assert store.find_thread(tenant_id=TENANT, run_id=run_id, rule_id=RULE, actor=ACTOR) is None
    assert (
        store.find_thread(tenant_id=TENANT, run_id=run_id, rule_id=MISSING_RULE, actor=ACTOR)
        is None
    )


def test_an_unknown_or_malformed_thread_id_is_reported(store: AssistantStore) -> None:
    for thread_id in (str(uuid.uuid4()), "not-a-uuid", ""):
        with pytest.raises(ThreadNotFound):
            store.require_thread(thread_id, tenant_id=TENANT)

    unknown = str(uuid.uuid4())
    with pytest.raises(ThreadNotFound):
        store.conversation(unknown, tenant_id=TENANT)
    with pytest.raises(ThreadNotFound):
        store.turn_count(unknown, tenant_id=TENANT)
    with pytest.raises(ThreadNotFound):
        store.close_thread(unknown, tenant_id=TENANT)
    with pytest.raises(ThreadNotFound):
        append(store, unknown)

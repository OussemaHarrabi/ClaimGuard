"""PostgreSQL persistence for the interactive assistant's conversations (migration 0011).

WHAT THIS MODULE OWNS
---------------------
The two tables ``0011_assistant_threads.sql`` creates, and nothing else:

*   :meth:`AssistantStore.open_thread` / :meth:`find_thread` / :meth:`require_thread` — one
    conversation per reviewer, on one finding of one run;
*   :meth:`AssistantStore.append_turn` — append the next turn of that conversation;
*   :meth:`AssistantStore.conversation` / :meth:`turn_count` — read it back, in order;
*   :meth:`AssistantStore.close_thread` — mark a conversation finished.

WHAT THIS MODULE DOES NOT OWN
-----------------------------
It never writes the run, its 15-key result records, its explanation provenance or the audit
ledger. The 15-key record is the frozen pack contract and the mentor's scorer rejects any extra
or missing key, so a conversation is a sidecar that READS a stored run
(:class:`~claimguard.review.store.ReviewStore` is the authority on that run) and stores its own
turns beside it. Nothing a reviewer asks an assistant can change a status, a severity, an
evidence pointer or a routing decision — there is no code path here that could.

WHY A REVIEWER GETS THEIR OWN THREAD
------------------------------------
``UNIQUE (tenant_id, run_id, rule_id, created_by)`` makes "open the conversation about this
finding" idempotent: a reviewer who clicks Explain twice resumes the same conversation instead
of forking a second one, and a colleague looking at the same finding never sees the first
reviewer's questions. :meth:`AssistantStore.open_thread` therefore upserts on that key rather
than inserting blindly, so two reviewers clicking at the same moment still get two threads and
one reviewer clicking twice still gets one.

WHY THE TURNS ARE APPEND-ONLY
-----------------------------
A turn is evidence of what a reviewer was told: the question, the model and prompt that
produced the answer, whether the verifier accepted it, and what stood in when it did not. A
rewritten turn would make "this reviewer was shown a verified answer" as unverifiable as a
rewritten status, so ``trg_assistant_turns_no_update`` refuses UPDATE at the database — the
store never issues one, and
:func:`tests.ai.test_assistant_store.test_a_stored_turn_cannot_be_updated` proves the refusal
rather than trusting the convention.

WHY ``seq`` IS ALLOCATED UNDER A ROW LOCK
-----------------------------------------
``UNIQUE (thread_id, seq)`` is only a guarantee if two writers cannot pick the same number.
A bare ``SELECT max(seq) + 1`` would let two concurrent appends both read the same maximum and
one of them then fail on the unique index — the conversation would lose a turn to a race.
:meth:`AssistantStore.append_turn` therefore takes the thread's row with ``FOR UPDATE`` first,
which serialises the appends of one conversation (and, in the same statement, proves the thread
exists and belongs to this tenant) while leaving different conversations fully parallel.

CONVENTIONS IT RESPECTS
-----------------------
*   The engine is injected, exactly as :class:`~claimguard.review.store.ReviewStore` takes it:
    no DSN resolution and no second session pattern here.
*   ``tenant_id`` is an argument of every method and a predicate of every statement, never
    something read back out of a row that was already fetched. A thread of another tenant is
    reported as :class:`ThreadNotFound`, the same answer as a thread that does not exist, so the
    API cannot be used to probe which thread ids are real.
*   The mapping of ``rule_runs`` / ``rule_results`` is imported from
    :mod:`claimguard.review.store` rather than redeclared: two mappings of one table drift.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final, Literal

from sqlalchemy import Column, MetaData, Table, Text, func, insert, select, update
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.types import INTEGER, TIMESTAMP

from claimguard.ai.schemas import AssistantConversation, AssistantThreadRef, AssistantTurn
from claimguard.review.store import RESULTS, RUNS

#: The Alembic revision this module's tables come from.
ASSISTANT_SCHEMA_REVISION: Final = "0011"

#: The unique constraint that makes ``open_thread`` idempotent per reviewer.
THREAD_OWNER_CONSTRAINT: Final = "uq_assistant_threads_owner"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AssistantStoreError(RuntimeError):
    """Base class for assistant-store failures the HTTP layer maps to a status code."""


class ThreadNotFound(AssistantStoreError):  # noqa: N818 - the API codes against these names
    """No such conversation — or one belonging to another tenant (the two are one answer)."""


class ThreadClosed(AssistantStoreError):  # noqa: N818 - the API codes against these names
    """The conversation is closed and accepts no further turns."""


class UnknownRun(AssistantStoreError):  # noqa: N818 - the API codes against these names
    """No run with that id for this tenant, or a claim id that is not that run's claim."""


class UnknownFinding(AssistantStoreError):  # noqa: N818 - the API codes against these names
    """The run has no result for that rule: there is no finding to explain."""


# ---------------------------------------------------------------------------
# Schema mapping (read + write; migrations remain the authority)
# ---------------------------------------------------------------------------

_ASSISTANT_METADATA = MetaData()

THREADS = Table(
    "assistant_threads",
    _ASSISTANT_METADATA,
    # Both ids are generated by the database (``DEFAULT gen_random_uuid()``); declaring the
    # server default here is what tells SQLAlchemy the primary key needs no value from us.
    Column(
        "thread_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    ),
    Column("tenant_id", Text, nullable=False),
    Column("run_id", Text, nullable=False),
    Column("claim_id", Text, nullable=False),
    Column("rule_id", Text, nullable=False),
    Column("created_by", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    Column("closed_at", TIMESTAMP(timezone=True)),
    schema="claimguard",
)

TURNS = Table(
    "assistant_turns",
    _ASSISTANT_METADATA,
    Column(
        "turn_id",
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    ),
    Column("thread_id", UUID(as_uuid=True), nullable=False),
    Column("tenant_id", Text, nullable=False),
    Column("seq", INTEGER, nullable=False),
    Column("role", Text, nullable=False),
    Column("question", Text),
    # ``none_as_null`` because "this turn carries no answer" (a reviewer's turn, a refusal)
    # has to be SQL NULL and not the JSON value ``null``: the migration's CHECK accepts only an
    # object, and an auditor reading the table must not have to tell two nulls apart.
    Column("answer", JSONB(none_as_null=True)),
    Column("verification", Text, nullable=False),
    Column("reasons", JSONB, nullable=False),
    Column("model_version", Text, nullable=False),
    Column("prompt_version", Text, nullable=False),
    Column("receipt", Text),
    Column("latency_ms", INTEGER),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    schema="claimguard",
)

#: Columns read/returned for a thread row (one definition, so the mapping and the
#: ``RETURNING`` clause cannot drift).
_THREAD_COLUMNS: Final[tuple[Any, ...]] = (
    THREADS.c.thread_id,
    THREADS.c.tenant_id,
    THREADS.c.run_id,
    THREADS.c.claim_id,
    THREADS.c.rule_id,
    THREADS.c.created_by,
    THREADS.c.created_at,
    THREADS.c.closed_at,
)

#: Columns read/returned for a turn row.
_TURN_COLUMNS: Final[tuple[Any, ...]] = (
    TURNS.c.turn_id,
    TURNS.c.thread_id,
    TURNS.c.seq,
    TURNS.c.role,
    TURNS.c.question,
    TURNS.c.answer,
    TURNS.c.verification,
    TURNS.c.reasons,
    TURNS.c.model_version,
    TURNS.c.prompt_version,
    TURNS.c.receipt,
    TURNS.c.latency_ms,
    TURNS.c.created_at,
)


# ---------------------------------------------------------------------------
# Narrowing helpers
# ---------------------------------------------------------------------------


def _thread_key(thread_id: str | uuid.UUID) -> uuid.UUID:
    """The thread id as a UUID; a malformed one is simply a thread that does not exist.

    ``/v1/ai/threads/{id}`` receives the id from the URL, so it can be anything. Parsing here
    keeps a nonsense id a 404 instead of letting psycopg raise a cast error the API would serve
    as a 500. An already-parsed id passes straight through, so a caller that has one does not
    normalise it twice.
    """
    if isinstance(thread_id, uuid.UUID):
        return thread_id
    try:
        return uuid.UUID(thread_id)
    except ValueError as error:
        raise ThreadNotFound(f"no such thread: {thread_id!r}") from error


def _turn_role(value: Any) -> Literal["reviewer", "assistant"]:
    """Narrow a role to the two the schema allows, whether it came from a caller or a row."""
    text = str(value)
    if text == "reviewer" or text == "assistant":
        return text
    raise AssistantStoreError(f"role must be 'reviewer' or 'assistant'; got {value!r}")


def _turn_verification(value: Any) -> Literal["accepted", "repaired", "fallback", "refused"]:
    """Narrow a verification to the four the schema allows, from a caller or a row."""
    text = str(value)
    if text == "repaired" or text == "fallback" or text == "refused" or text == "accepted":
        return text
    raise AssistantStoreError(
        f"verification must be 'accepted', 'repaired', 'fallback' or 'refused'; got {value!r}"
    )


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------


def _thread_from_row(row: Any) -> AssistantThreadRef:
    """Rebuild one conversation identity from its stored row."""
    return AssistantThreadRef(
        thread_id=str(row.thread_id),
        tenant_id=str(row.tenant_id),
        run_id=str(row.run_id),
        claim_id=str(row.claim_id),
        rule_id=str(row.rule_id),
        created_by=str(row.created_by),
        created_at=row.created_at,
        closed_at=None if row.closed_at is None else row.closed_at,
    )


def _turn_from_row(row: Any) -> AssistantTurn:
    """Rebuild one stored turn from its row.

    The two enumerated columns are narrowed rather than coerced: a row whose ``role`` or
    ``verification`` is not one of the documented values is corrupt, and quietly relabelling it
    would hide exactly the fact an auditor would need.
    """
    return AssistantTurn(
        turn_id=str(row.turn_id),
        thread_id=str(row.thread_id),
        sequence=int(row.seq),
        role=_turn_role(row.role),
        question=None if row.question is None else str(row.question),
        answer=None if row.answer is None else dict(row.answer),
        verification=_turn_verification(row.verification),
        reasons=[str(reason) for reason in row.reasons],
        model_version=str(row.model_version),
        prompt_version=str(row.prompt_version),
        receipt=None if row.receipt is None else str(row.receipt),
        latency_ms=None if row.latency_ms is None else int(row.latency_ms),
        created_at=row.created_at,
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class AssistantStore:
    """All interactive-assistant persistence, over the review workflow's injected engine."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # -- threads --------------------------------------------------------

    def open_thread(
        self,
        *,
        tenant_id: str,
        run_id: str,
        claim_id: str,
        rule_id: str,
        actor: str,
    ) -> AssistantThreadRef:
        """Get or create the reviewer's conversation about one finding of one run.

        Idempotent on ``(tenant_id, run_id, rule_id, created_by)``: the same reviewer reopening
        the same finding gets the same conversation and the same ``created_at``. An already
        closed conversation is returned as it is — reopening it is the API's decision, not a
        side effect of asking for the thread.
        """
        with self._engine.begin() as connection:
            self._require_finding(
                connection,
                tenant_id=tenant_id,
                run_id=run_id,
                claim_id=claim_id,
                rule_id=rule_id,
            )
            insertion = pg_insert(THREADS).values(
                tenant_id=tenant_id,
                run_id=run_id,
                claim_id=claim_id,
                rule_id=rule_id,
                created_by=actor,
                created_at=func.now(),
            )
            row = connection.execute(
                insertion.on_conflict_do_update(
                    constraint=THREAD_OWNER_CONSTRAINT,
                    # A no-op assignment: the conflicting row already carries this value, and
                    # ``DO UPDATE`` is what makes the existing row come back through RETURNING
                    # without a second round trip that could race the first writer's commit.
                    set_={"created_by": insertion.excluded.created_by},
                ).returning(*_THREAD_COLUMNS)
            ).one()
        return _thread_from_row(row)

    def find_thread(
        self, *, tenant_id: str, run_id: str, rule_id: str, actor: str
    ) -> AssistantThreadRef | None:
        """The reviewer's conversation about that finding, or None when they have not opened one."""
        with self._engine.connect() as connection:
            row = connection.execute(
                select(*_THREAD_COLUMNS)
                .where(
                    THREADS.c.tenant_id == tenant_id,
                    THREADS.c.run_id == run_id,
                    THREADS.c.rule_id == rule_id,
                    THREADS.c.created_by == actor,
                )
                .limit(1)
            ).one_or_none()
        return None if row is None else _thread_from_row(row)

    def require_thread(self, thread_id: str, *, tenant_id: str) -> AssistantThreadRef:
        """One conversation, or :class:`ThreadNotFound` when this tenant cannot see it."""
        with self._engine.connect() as connection:
            row = self._require_thread_row(connection, thread_id, tenant_id=tenant_id)
        return _thread_from_row(row)

    def close_thread(self, thread_id: str, *, tenant_id: str) -> AssistantThreadRef:
        """Mark a conversation finished. Idempotent: the first closing time stands."""
        key = _thread_key(thread_id)
        with self._engine.begin() as connection:
            row = self._lock_thread(connection, key, tenant_id=tenant_id)
            if row.closed_at is None:
                row = connection.execute(
                    update(THREADS)
                    .where(
                        THREADS.c.thread_id == key,
                        THREADS.c.tenant_id == tenant_id,
                        THREADS.c.closed_at.is_(None),
                    )
                    .values(closed_at=func.now())
                    .returning(*_THREAD_COLUMNS)
                ).one()
        return _thread_from_row(row)

    # -- turns ----------------------------------------------------------

    def append_turn(
        self,
        thread_id: str,
        *,
        tenant_id: str,
        role: str,
        question: str | None,
        answer: Mapping[str, Any] | None,
        verification: str,
        reasons: Sequence[str],
        model_version: str,
        prompt_version: str,
        receipt: str | None,
        latency_ms: int | None,
    ) -> AssistantTurn:
        """Append the next turn and return it exactly as stored.

        The stored row is returned rather than the arguments echoed back, so the caller serves
        the real ``turn_id``, ``created_at`` and — the one value this store decides — the
        ``sequence``. The answer's five keys are NOT re-validated here: the verifier
        (:mod:`claimguard.edu.explain.verifier`) owns that judgement upstream, and a store that
        rewrote an answer on the way in would leave "what was this reviewer shown?" unanswerable.
        """
        role_value = _turn_role(role)
        verification_value = _turn_verification(verification)
        if not model_version.strip() or not prompt_version.strip():
            raise AssistantStoreError("model_version and prompt_version must not be blank")
        key = _thread_key(thread_id)
        with self._engine.begin() as connection:
            thread_row = self._lock_thread(connection, key, tenant_id=tenant_id)
            if thread_row.closed_at is not None:
                raise ThreadClosed(
                    f"thread {thread_id} was closed at {thread_row.closed_at.isoformat()}"
                )
            sequence = int(
                connection.execute(
                    select(func.coalesce(func.max(TURNS.c.seq), 0) + 1).where(
                        TURNS.c.thread_id == key
                    )
                ).scalar_one()
            )
            row = connection.execute(
                insert(TURNS)
                .values(
                    thread_id=key,
                    tenant_id=tenant_id,
                    seq=sequence,
                    role=role_value,
                    question=question,
                    answer=None if answer is None else dict(answer),
                    verification=verification_value,
                    reasons=list(reasons),
                    model_version=model_version,
                    prompt_version=prompt_version,
                    receipt=receipt,
                    latency_ms=latency_ms,
                    created_at=func.now(),
                )
                .returning(*_TURN_COLUMNS)
            ).one()
        return _turn_from_row(row)

    def conversation(self, thread_id: str, *, tenant_id: str) -> AssistantConversation:
        """The conversation and every turn in it, oldest first."""
        key = _thread_key(thread_id)
        with self._engine.connect() as connection:
            thread_row = self._require_thread_row(connection, key, tenant_id=tenant_id)
            rows = connection.execute(
                select(*_TURN_COLUMNS)
                .where(TURNS.c.thread_id == key, TURNS.c.tenant_id == tenant_id)
                .order_by(TURNS.c.seq)
            ).all()
        return AssistantConversation(
            thread=_thread_from_row(thread_row),
            turns=[_turn_from_row(row) for row in rows],
        )

    def turn_count(self, thread_id: str, *, tenant_id: str) -> int:
        """How many turns the conversation holds — the exact count, for the caller's own limit.

        The thread limit is the interface's rule (``MAX_TURNS_PER_THREAD`` is a limit on the
        reviewer's input, not a database invariant), so it is not enforced here; this count is
        what makes it enforceable without a query the API would have to write itself.
        """
        key = _thread_key(thread_id)
        with self._engine.connect() as connection:
            self._require_thread_row(connection, key, tenant_id=tenant_id)
            return int(
                connection.execute(
                    select(func.count())
                    .select_from(TURNS)
                    .where(TURNS.c.thread_id == key, TURNS.c.tenant_id == tenant_id)
                ).scalar_one()
            )

    # -- statements -----------------------------------------------------

    def _require_finding(
        self,
        connection: Connection,
        *,
        tenant_id: str,
        run_id: str,
        claim_id: str,
        rule_id: str,
    ) -> None:
        """Refuse a conversation about something this tenant's run does not contain.

        The database cannot check this for us: ``assistant_threads`` carries ``run_id`` and
        ``claim_id`` as plain columns and its foreign key names only ``run_id``, and
        ``rule_id`` is only checked against the shape ``R001..R015``. Validating here is what
        keeps a thread from claiming a run, a claim or a finding that the tenant does not own —
        the exact confusion a sidecar table invites.
        """
        run = connection.execute(
            select(RUNS.c.claim_id).where(RUNS.c.tenant_id == tenant_id, RUNS.c.run_id == run_id)
        ).one_or_none()
        if run is None:
            raise UnknownRun(f"no run {run_id} for tenant {tenant_id}")
        if str(run.claim_id) != claim_id:
            raise UnknownRun(f"run {run_id} belongs to claim {run.claim_id}, not {claim_id}")
        finding = connection.execute(
            select(RESULTS.c.rule_id)
            .where(
                RESULTS.c.tenant_id == tenant_id,
                RESULTS.c.run_id == run_id,
                RESULTS.c.rule_id == rule_id,
            )
            .limit(1)
        ).one_or_none()
        if finding is None:
            raise UnknownFinding(f"run {run_id} has no result for {rule_id}")

    def _require_thread_row(
        self, connection: Connection, thread_id: str | uuid.UUID, *, tenant_id: str
    ) -> Any:
        """The tenant's thread row, or :class:`ThreadNotFound` (never another tenant's row)."""
        row = connection.execute(
            select(*_THREAD_COLUMNS)
            .where(THREADS.c.thread_id == _thread_key(thread_id), THREADS.c.tenant_id == tenant_id)
            .limit(1)
        ).one_or_none()
        if row is None:
            raise ThreadNotFound(f"no thread {thread_id} for tenant {tenant_id}")
        return row

    def _lock_thread(self, connection: Connection, key: uuid.UUID, *, tenant_id: str) -> Any:
        """Take the thread's row for the rest of this transaction, tenant-scoped.

        The lock is what makes ``max(seq) + 1`` safe: a second append to the same conversation
        waits here until the first commits, then reads the sequence the first one wrote. It is
        also the existence-and-ownership check for writers, so no separate selection is needed.
        """
        row = connection.execute(
            select(*_THREAD_COLUMNS)
            .where(THREADS.c.thread_id == key, THREADS.c.tenant_id == tenant_id)
            .with_for_update()
        ).one_or_none()
        if row is None:
            raise ThreadNotFound(f"no thread {key} for tenant {tenant_id}")
        return row

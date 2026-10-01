"""The interactive assistant on the authenticated review HTTP surface.

WHAT THIS FILE PROVES
---------------------
The four assistant routes are part of the review surface, not a second, softer
door into it. No session is 401; a role that may not read a claim is 403; a
thread of another tenant and a thread of another reviewer are both 404 — a
caller may pass an id that exists elsewhere as validly as one that never
existed, and the two must be indistinguishable from outside; a closed thread and
a conversation at its turn limit are 409.

The feature must also work with **no model configured**, which is the normal
deployment: the reviewer gets the deterministic explanation, stored and served
with ``verification='fallback'``, and the endpoint never 500s because no model
is reachable. ``GET /v1/ai/status`` is the honest report of that state — and it
keeps answering when the optional ``agent`` extra is absent entirely, while the
conversation routes say 503 and name the extra.

HOW IT STAYS OFFLINE
--------------------
*   No PostgreSQL. The review store and the assistant store are in-memory fakes
    of the same two contracts (each real store's own behaviour is proved where
    that store lives); the engine the fake review store inherits is never
    connected.
*   No model and no socket. The assistant package's ``answer_question`` is
    replaced by a recording stub, so every assertion here is about what the API
    *assembled and stored* — the stored finding, the original envelope, the rule
    manifest, the claim's policy profile, the history — never about a model's
    wording.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final, cast

import httpx
import pytest
from claimguard.ai import graph as graph_module
from claimguard.ai.errors import AssistantInputError
from claimguard.ai.graph import AssistantOutcome
from claimguard.ai.schemas import (
    MAX_TURNS_PER_THREAD,
    AssistantConversation,
    AssistantStatus,
    AssistantThreadRef,
    AssistantTurn,
    TurnRole,
    Verification,
)
from claimguard.ai.store import ThreadClosed, ThreadNotFound
from claimguard.clinic.access import PERMISSIONS, Action, Role
from claimguard.clinic.directory import ClinicDirectory
from claimguard.clinic.session import SessionSigner
from claimguard.edu.emit import validate_record
from claimguard.edu.engine import evaluate_claim
from claimguard.edu.envelope import ResultRecord
from claimguard.edu.explain.fallback import build_explanation
from claimguard.review.app import create_app
from claimguard.review.explanations import TemplateExplanationProvider
from claimguard.review.models import RuleRun
from claimguard.review.store import (
    ReviewStore,
    build_engine,
    envelope_digest,
    new_run_id,
    new_trace_id,
)

from tests.edu import RULES_DIR, base_claim, rules_context

pytestmark = pytest.mark.unit

#: The tenant and reviewer these tests sign in as.
TENANT: Final = "clinic-legacy-demo"
USER_ID: Final = "rev-assistant-1"
OTHER_USER: Final = "rev-assistant-2"

#: The run in this file fails R003 (coverage ends before the service date).
FLAGGED_RULE: Final = "R003"

#: A DSN nothing ever connects to: the fake store inherits ``ReviewStore`` for its
#: shape and its ``.engine``, and overrides every method that would read.
UNUSED_DSN: Final = "postgresql+psycopg://claimguard:claimguard@127.0.0.1:1/claimguard"

SIGNER: Final = SessionSigner(b"test-key-for-assistant-api-0123456789")


# ---------------------------------------------------------------------------
# The stored run (no database)
# ---------------------------------------------------------------------------


def _coverage_lapse() -> dict[str, Any]:
    """A claim whose only failing check is R003."""
    envelope = base_claim()
    envelope["claim_id"] = "CG-ASSISTANT-API-0001"
    envelope["invoice_number"] = f"INV-{envelope['claim_id']}"
    envelope["coverage"]["coverage_id"] = f"COV-{envelope['claim_id']}"
    envelope["coverage"]["end_date"] = "2026-03-09"  # the service date is 2026-03-10
    return envelope


@pytest.fixture(scope="module")
def stored_run() -> tuple[dict[str, Any], RuleRun, list[ResultRecord]]:
    """One engine run over one claim, with the 15 records the engine produced."""
    envelope = _coverage_lapse()
    # The engine emits mappings; the store persists and serves them as the
    # frozen 15-key contract, so the fake store holds what the real one returns.
    records = [validate_record(raw, envelope) for raw in evaluate_claim(envelope, rules_context())]
    run = RuleRun(
        run_id=new_run_id(),
        claim_id=str(envelope["claim_id"]),
        version=1,
        input_hash=envelope_digest(envelope),
        trace_id=new_trace_id(),
        rule_version="1.0.0",
        model_version="deterministic-template",
        prompt_version="explain-1.0.0",
        initiated_by="api-submit",
        created_at=datetime.now(UTC),
    )
    return envelope, run, records


class FakeReviewStore(ReviewStore):
    """The run, its records and its envelope — canned, with no connection.

    The assistant reads a stored run through exactly the methods the reviewer
    endpoints use, so the fake implements those and nothing else. The inherited
    engine exists only because ``ReviewStore`` requires one; no statement is
    ever issued against it.
    """

    def __init__(
        self, run: RuleRun, records: Sequence[ResultRecord], envelope: Mapping[str, Any]
    ) -> None:
        super().__init__(build_engine(UNUSED_DSN))
        self._run = run
        self._records = list(records)
        self._envelope = dict(envelope)

    @property
    def run(self) -> RuleRun:
        """The canned run."""
        return self._run

    @property
    def envelope(self) -> dict[str, Any]:
        """The canned claim input, as the store would serve it."""
        return dict(self._envelope)

    def for_tenant(self, tenant_id: str) -> ReviewStore:
        """The canned rows are the one tenant these tests use."""
        return self

    def ensure_schema(self) -> None:
        """The canned rows need no migration."""

    def get_run(self, run_id: str) -> RuleRun | None:
        return self._run if run_id == self._run.run_id else None

    def get_results(self, run_id: str) -> list[ResultRecord]:
        return list(self._records) if run_id == self._run.run_id else []

    def get_claim_envelope(self, run_id: str) -> dict[str, Any] | None:
        return dict(self._envelope) if run_id == self._run.run_id else None


# ---------------------------------------------------------------------------
# The assistant store (no database)
# ---------------------------------------------------------------------------


class FakeAssistantStore:
    """The ``AssistantStore`` contract, in memory.

    It mirrors the real store's published behaviour: ``tenant_id`` on every call,
    one thread per (tenant, run, rule, reviewer), ``ThreadNotFound`` for an
    unknown thread *and* for another tenant's thread (never a different error),
    ``ThreadClosed`` for a write to a closed thread, and store-allocated turn
    sequences. ``placebo_turns`` stands in for history recorded before the test
    started, so the turn limit can be reached without posting 40 messages.
    """

    def __init__(self) -> None:
        self.threads: dict[str, AssistantThreadRef] = {}
        self.turns: dict[str, list[AssistantTurn]] = {}
        self.turn_sequences: dict[str, int] = {}
        self.placebo_turns: int = 0

    def open_thread(
        self, *, tenant_id: str, run_id: str, claim_id: str, rule_id: str, actor: str
    ) -> AssistantThreadRef:
        for thread in self.threads.values():
            if (thread.tenant_id, thread.run_id, thread.rule_id, thread.created_by) == (
                tenant_id,
                run_id,
                rule_id,
                actor,
            ):
                return thread
        thread = AssistantThreadRef(
            thread_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            run_id=run_id,
            claim_id=claim_id,
            rule_id=rule_id,
            created_by=actor,
            created_at=datetime.now(UTC),
        )
        self.threads[thread.thread_id] = thread
        self.turns[thread.thread_id] = []
        self.turn_sequences[thread.thread_id] = 0
        return thread

    def require_thread(self, thread_id: str, *, tenant_id: str) -> AssistantThreadRef:
        thread = self.threads.get(thread_id)
        if thread is None or thread.tenant_id != tenant_id:
            raise ThreadNotFound(f"unknown thread: {thread_id}")
        return thread

    def turn_count(self, thread_id: str, *, tenant_id: str) -> int:
        self.require_thread(thread_id, tenant_id=tenant_id)
        return len(self.turns[thread_id]) + self.placebo_turns

    def append_turn(
        self,
        thread_id: str,
        *,
        tenant_id: str,
        role: TurnRole,
        question: str | None,
        answer: Mapping[str, Any] | None,
        verification: Verification,
        reasons: Sequence[str],
        model_version: str,
        prompt_version: str,
        receipt: str | None,
        latency_ms: int | None,
    ) -> AssistantTurn:
        thread = self.require_thread(thread_id, tenant_id=tenant_id)
        if thread.closed_at is not None:
            raise ThreadClosed(f"thread {thread_id} is closed")
        sequence = self.turn_sequences[thread_id] + 1
        self.turn_sequences[thread_id] = sequence
        turn = AssistantTurn(
            turn_id=str(uuid.uuid4()),
            thread_id=thread_id,
            sequence=sequence,
            role=role,
            question=question,
            answer=None if answer is None else dict(answer),
            verification=verification,
            reasons=list(reasons),
            model_version=model_version,
            prompt_version=prompt_version,
            receipt=receipt,
            latency_ms=latency_ms,
            created_at=datetime.now(UTC),
        )
        self.turns[thread_id].append(turn)
        return turn

    def conversation(self, thread_id: str, *, tenant_id: str) -> AssistantConversation:
        thread = self.require_thread(thread_id, tenant_id=tenant_id)
        return AssistantConversation(thread=thread, turns=list(self.turns[thread_id]))

    def close(self, thread_id: str, *, tenant_id: str) -> None:
        """Close a thread the way the assistant package's store would."""
        thread = self.require_thread(thread_id, tenant_id=tenant_id)
        self.threads[thread_id] = thread.model_copy(update={"closed_at": datetime.now(UTC)})


# ---------------------------------------------------------------------------
# The model call (no model)
# ---------------------------------------------------------------------------


class RecordingGraph:
    """``answer_question``, recording every call and answering with a fixed outcome."""

    def __init__(self, outcome: AssistantOutcome) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> AssistantOutcome:
        self.calls.append(kwargs)
        return self.outcome


def fallback_outcome(finding: Mapping[str, Any], rule: Mapping[str, Any]) -> AssistantOutcome:
    """Exactly what the assistant returns when no model is configured."""
    return AssistantOutcome(
        answer=build_explanation(finding, rule),
        verification="fallback",
        reasons=("no model is configured in this deployment",),
        model_version="none",
        prompt_version="assistant-1.0.0",
        receipt=None,
        latency_ms=0,
    )


# ---------------------------------------------------------------------------
# The signed-in surface
# ---------------------------------------------------------------------------


class FakeDirectory:
    """Membership without a database — the middleware's only dependency."""

    def __init__(self, role: Role) -> None:
        self._role = role

    def membership(self, user_id: str, tenant_id: str) -> Role | None:
        return self._role if tenant_id == TENANT else None


def build_app(
    *,
    store: ReviewStore,
    assistant: FakeAssistantStore | None = None,
    role: Role = Role.RCM_LEAD,
) -> Any:
    """The review API with no database and no model.

    The directory is a cast rather than a subclass because the middleware uses
    one method of it (``membership``); everything else about a clinic is out of
    scope here.
    """
    return create_app(
        store=store,
        rules_dir=RULES_DIR,
        explain_provider=TemplateExplanationProvider(),
        signer=SIGNER,
        directory=cast(ClinicDirectory, FakeDirectory(role)),
        assistant_store=assistant,
    )


def client_for(app: Any, *, signed_in: bool = True) -> httpx.AsyncClient:
    """An in-process client, signed in unless the test says otherwise."""
    cookies = {"claimguard_session": SIGNER.issue(USER_ID, TENANT)} if signed_in else {}
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://review.test",
        cookies=cookies,
    )


@pytest.fixture
def review_store(
    stored_run: tuple[dict[str, Any], RuleRun, list[ResultRecord]],
) -> FakeReviewStore:
    envelope, run, records = stored_run
    return FakeReviewStore(run, records, envelope)


@pytest.fixture
def assistant_store() -> FakeAssistantStore:
    return FakeAssistantStore()


@pytest.fixture
def stub_graph(
    monkeypatch: pytest.MonkeyPatch,
    stored_run: tuple[dict[str, Any], RuleRun, list[ResultRecord]],
) -> RecordingGraph:
    """Replace the assistant package's model call with a recording stub."""
    _, _, records = stored_run
    finding = next(record for record in records if record.rule_id == FLAGGED_RULE)
    graph = RecordingGraph(
        fallback_outcome(
            finding.model_dump(mode="json"),
            rules_context().rule(FLAGGED_RULE).model_dump(mode="json"),
        )
    )
    monkeypatch.setattr(graph_module, "answer_question", graph)
    return graph


async def _explain(client: httpx.AsyncClient, run_id: str, *, question: str | None = None) -> Any:
    """POST the explain route, with a body only when a question was given."""
    body = None if question is None else {"question": question}
    return await client.post(f"/v1/runs/{run_id}/findings/{FLAGGED_RULE}/explain", json=body)


# ---------------------------------------------------------------------------
# Authentication and permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_assistant_routes_require_a_session(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app, signed_in=False) as client:
        status = await client.get("/v1/ai/status")
        explain = await _explain(client, review_store.run.run_id)
        messages = await client.post("/v1/threads/whatever/messages", json={"question": "why?"})
        thread = await client.get("/v1/threads/whatever")
    assert [status.status_code, explain.status_code, messages.status_code, thread.status_code] == [
        401,
        401,
        401,
        401,
    ]
    assert stub_graph.calls == []


@pytest.mark.asyncio
async def test_a_role_that_cannot_read_a_claim_cannot_ask_the_assistant(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    app = build_app(store=review_store, assistant=assistant_store, role=Role.TECHNICAL_MANAGER)
    async with client_for(app) as client:
        status = await client.get("/v1/ai/status")
        explain = await _explain(client, review_store.run.run_id)
        messages = await client.post("/v1/threads/whatever/messages", json={"question": "why?"})
    assert [status.status_code, explain.status_code, messages.status_code] == [403, 403, 403]
    assert stub_graph.calls == []


def test_the_claim_reading_roles_may_ask_and_the_technician_may_not() -> None:
    """The permission matrix, stated once so a regression is unambiguous."""
    may_ask = {role for role, actions in PERMISSIONS.items() if Action.ASK_ASSISTANT in actions}
    assert may_ask == {Role.RCM_REVIEWER, Role.RCM_LEAD, Role.CLINIC_ADMIN}


# ---------------------------------------------------------------------------
# Status: honest about the deployment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_serves_what_the_assistant_reports(
    review_store: FakeReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route transports the status verbatim — it invents no mode or detail."""
    reported = AssistantStatus(
        enabled=False,
        mode="off",
        model="none",
        prompt_version="assistant-1.0.0",
        detail="no model is configured: set CLAIMGUARD_AI_MODE or provide a key",
    )

    def status_stub() -> AssistantStatus:
        return reported

    monkeypatch.setattr(graph_module, "assistant_status", status_stub)
    app = build_app(store=review_store)
    async with client_for(app) as client:
        response = await client.get("/v1/ai/status")
    assert response.status_code == 200
    assert response.json() == reported.model_dump(mode="json")


@pytest.mark.asyncio
async def test_status_still_answers_when_the_agent_extra_is_absent(
    review_store: FakeReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployment without the optional extra reports itself off, not 503."""
    monkeypatch.setitem(sys.modules, "claimguard.ai.graph", None)
    app = build_app(store=review_store)
    async with client_for(app) as client:
        response = await client.get("/v1/ai/status")
    assert response.status_code == 200
    body = AssistantStatus.model_validate(response.json())
    assert body.enabled is False
    assert body.mode == "off"
    assert "agent" in body.detail


@pytest.mark.asyncio
async def test_the_conversation_routes_say_503_when_the_extra_is_absent(
    review_store: FakeReviewStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A conversation the deployment cannot serve names what to install."""
    monkeypatch.setitem(sys.modules, "claimguard.ai.store", None)
    app = build_app(store=review_store)
    async with client_for(app) as client:
        response = await _explain(client, review_store.run.run_id)
    assert response.status_code == 503
    assert "agent" in response.json()["detail"]


@pytest.mark.asyncio
async def test_the_model_call_reports_503_when_only_the_graph_is_absent(
    review_store: FakeReviewStore,
    assistant_store: FakeAssistantStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stubbed store is injectable, but the missing model call is still honest."""
    monkeypatch.setitem(sys.modules, "claimguard.ai.graph", None)
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        response = await _explain(client, review_store.run.run_id)
    assert response.status_code == 503
    assert "agent" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Explain: the opening turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explain_answers_from_the_deterministic_layer(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    run = review_store.run
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        response = await _explain(client, run.run_id)
    assert response.status_code == 200
    conversation = AssistantConversation.model_validate(response.json())
    assert conversation.thread.run_id == run.run_id
    assert conversation.thread.rule_id == FLAGGED_RULE
    assert conversation.thread.claim_id == run.claim_id
    assert conversation.thread.created_by == USER_ID
    assert [turn.role for turn in conversation.turns] == ["assistant"]
    opening = conversation.turns[0]
    assert opening.sequence == 1
    assert opening.verification == "fallback"
    assert opening.question is None
    assert opening.model_version == "none"
    assert opening.reasons == ["no model is configured in this deployment"]
    assert opening.answer is not None
    assert set(opening.answer) == {
        "explanation",
        "correction_recommendation",
        "cited_evidence_paths",
        "cited_rule_ids",
        "needs_human_review",
    }
    assert opening.answer["cited_rule_ids"] == [FLAGGED_RULE]


@pytest.mark.asyncio
async def test_the_explain_route_accepts_the_empty_body_the_interface_sends(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    """The body the reviewer's click actually produces, not the one we wish it produced.

    The interface builds ``question ? {question} : {}`` and posts it, so opening a conversation
    sends an EMPTY OBJECT. A request model with a required field answers 422 before the handler
    runs, which makes the button fail in the browser - and neither side's tests caught it, because
    these tests sent no body at all while the interface's tests mocked fetch. Calling the real
    server did.
    """
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        response = await client.post(
            f"/v1/runs/{review_store.run.run_id}/findings/{FLAGGED_RULE}/explain", json={}
        )
    assert response.status_code == 200
    conversation = AssistantConversation.model_validate(response.json())
    assert conversation.turns[0].question is None
    assert conversation.turns[0].verification == "fallback"


@pytest.mark.asyncio
async def test_a_blank_question_is_refused_on_the_opening_route_too(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    """Absent is legal; blank is a client mistake, and both routes agree about that."""
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        response = await client.post(
            f"/v1/runs/{review_store.run.run_id}/findings/{FLAGGED_RULE}/explain",
            json={"question": "   "},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_explain_hands_the_assistant_the_stored_run_it_was_given(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    """The integration: the finding, the ORIGINAL envelope, the rule, the policy."""
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        response = await _explain(client, review_store.run.run_id, question="  why   R003?  ")
    assert response.status_code == 200
    assert len(stub_graph.calls) == 1
    call = stub_graph.calls[0]
    assert call["finding"]["rule_id"] == FLAGGED_RULE
    # The envelope is the one the reviewer's own claim endpoint serves, verbatim:
    # a re-coerced copy would make valid evidence pointers look broken.
    assert call["envelope"] == review_store.envelope
    assert call["rule"]["rule_id"] == FLAGGED_RULE
    assert call["policy"]["policy_id"] == review_store.envelope["policy_id"]
    # The submitted body's own contract strips surrounding whitespace (it does
    # not rewrite the question); what the reviewer typed is what is stored.
    assert call["question"] == "why   R003?"
    assert call["history"] == []
    conversation = AssistantConversation.model_validate(response.json())
    assert conversation.turns[0].question == "why   R003?"


@pytest.mark.asyncio
async def test_explain_resumes_the_same_thread_on_a_second_click(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    """A reviewer who clicks Explain twice keeps one conversation, not two."""
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        first = await _explain(client, review_store.run.run_id)
        second = await _explain(client, review_store.run.run_id)
    assert first.json()["thread"]["thread_id"] == second.json()["thread"]["thread_id"]
    assert len(assistant_store.threads) == 1


# ---------------------------------------------------------------------------
# Messages: the follow-up turn, the limit and the leak-free 404
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_follow_up_stores_the_reviewer_turn_and_the_answer(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        opened = await _explain(client, review_store.run.run_id)
        thread_id = opened.json()["thread"]["thread_id"]
        response = await client.post(
            f"/v1/threads/{thread_id}/messages", json={"question": "what evidence supports it?"}
        )
    assert response.status_code == 200
    conversation = AssistantConversation.model_validate(response.json())
    assert [turn.role for turn in conversation.turns] == ["assistant", "reviewer", "assistant"]
    assert [turn.sequence for turn in conversation.turns] == [1, 2, 3]
    asked, answered = conversation.turns[1], conversation.turns[2]
    assert asked.question == "what evidence supports it?"
    assert asked.answer is None
    assert answered.question == "what evidence supports it?"
    assert answered.verification == "fallback"
    # The assistant is given the conversation so far and the new question once:
    # the reviewer turn is stored after the answer, so it reaches the NEXT call's
    # history rather than being sent twice to this one.
    assert stub_graph.calls[1]["history"] == [
        {"role": "assistant", "question": None, "answer": conversation.turns[0].answer}
    ]
    assert stub_graph.calls[1]["question"] == "what evidence supports it?"


@pytest.mark.asyncio
async def test_get_returns_the_thread_and_every_turn(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        opened = await _explain(client, review_store.run.run_id, question="what does R003 check?")
        thread_id = opened.json()["thread"]["thread_id"]
        response = await client.get(f"/v1/threads/{thread_id}")
    assert response.status_code == 200
    assert response.json() == opened.json()
    assert stub_graph.calls[0]["question"] == "what does R003 check?"


@pytest.mark.asyncio
async def test_a_thread_of_another_tenant_is_not_found(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    """404, never 403: whether an id exists elsewhere is not the caller's business."""
    foreign = assistant_store.open_thread(
        tenant_id="another-clinic",
        run_id=review_store.run.run_id,
        claim_id=review_store.run.claim_id,
        rule_id=FLAGGED_RULE,
        actor=USER_ID,
    )
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        read = await client.get(f"/v1/threads/{foreign.thread_id}")
        wrote = await client.post(
            f"/v1/threads/{foreign.thread_id}/messages", json={"question": "why?"}
        )
    assert [read.status_code, wrote.status_code] == [404, 404]
    assert "another-clinic" not in read.text
    assert stub_graph.calls == []


@pytest.mark.asyncio
async def test_another_reviewers_thread_is_not_found(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    """A conversation is personal; a colleague's thread is as invisible as a stranger's."""
    colleague = assistant_store.open_thread(
        tenant_id=TENANT,
        run_id=review_store.run.run_id,
        claim_id=review_store.run.claim_id,
        rule_id=FLAGGED_RULE,
        actor=OTHER_USER,
    )
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        read = await client.get(f"/v1/threads/{colleague.thread_id}")
        wrote = await client.post(
            f"/v1/threads/{colleague.thread_id}/messages", json={"question": "why?"}
        )
    assert [read.status_code, wrote.status_code] == [404, 404]
    assert stub_graph.calls == []


@pytest.mark.asyncio
async def test_a_closed_thread_refuses_a_new_message(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        opened = await _explain(client, review_store.run.run_id)
        thread_id = opened.json()["thread"]["thread_id"]
        assistant_store.close(thread_id, tenant_id=TENANT)
        response = await client.post(f"/v1/threads/{thread_id}/messages", json={"question": "why?"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_a_conversation_at_its_limit_is_refused_before_the_model_is_asked(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        opened = await _explain(client, review_store.run.run_id)
        thread_id = opened.json()["thread"]["thread_id"]
        calls_after_opening = len(stub_graph.calls)
        # One more turn would be the 41st: two short of the limit is the last
        # follow-up a thread may hold, and the next one must be refused.
        assistant_store.placebo_turns = MAX_TURNS_PER_THREAD - 1
        response = await client.post(f"/v1/threads/{thread_id}/messages", json={"question": "why?"})
    assert response.status_code == 409
    assert str(MAX_TURNS_PER_THREAD) in response.json()["detail"]
    assert len(stub_graph.calls) == calls_after_opening


# ---------------------------------------------------------------------------
# The finding has to be one of the run's
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_conversation_exactly_at_its_limit_still_accepts_the_last_turn(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    """The limit is inclusive: turn 40 may be written, turn 41 may not."""
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        opened = await _explain(client, review_store.run.run_id)
        thread_id = opened.json()["thread"]["thread_id"]
        # The opening turn counts: 1 stored + 37 imaginary + these 2 == 40.
        assistant_store.placebo_turns = MAX_TURNS_PER_THREAD - 3
        response = await client.post(f"/v1/threads/{thread_id}/messages", json={"question": "why?"})
    assert response.status_code == 200
    conversation = AssistantConversation.model_validate(response.json())
    assert [turn.sequence for turn in conversation.turns] == [1, 2, 3]


@pytest.mark.asyncio
async def test_an_unknown_finding_of_a_known_run_is_not_found(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    """R001 is part of every run; a rule id that is not is a 404, not an answer."""
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        response = await client.post(f"/v1/runs/{review_store.run.run_id}/findings/NOPE-99/explain")
    assert response.status_code == 404
    assert "NOPE-99" in response.json()["detail"]
    assert stub_graph.calls == []


@pytest.mark.asyncio
async def test_an_unknown_run_is_not_found(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        response = await _explain(client, "RUN-" + "0" * 32)
    assert response.status_code == 404
    assert stub_graph.calls == []


@pytest.mark.asyncio
async def test_a_finding_the_assistant_cannot_use_is_reported_as_a_server_failure(
    review_store: FakeReviewStore,
    assistant_store: FakeAssistantStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stored record the assistant cannot explain is our defect, not the caller's."""

    def refusing(**kwargs: Any) -> AssistantOutcome:
        raise AssistantInputError("the finding carries no evidence pointers")

    monkeypatch.setattr(graph_module, "answer_question", refusing)
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        response = await _explain(client, review_store.run.run_id)
    assert response.status_code == 500
    assert "could not use this finding" in response.json()["detail"]


@pytest.mark.asyncio
async def test_a_blank_question_is_refused(
    review_store: FakeReviewStore, assistant_store: FakeAssistantStore, stub_graph: RecordingGraph
) -> None:
    app = build_app(store=review_store, assistant=assistant_store)
    async with client_for(app) as client:
        response = await client.post(
            f"/v1/runs/{review_store.run.run_id}/findings/{FLAGGED_RULE}/explain",
            json={"question": "   "},
        )
    assert response.status_code == 422
    assert stub_graph.calls == []

"""P2 telemetry — the four interactive assistant routes.

WHAT THIS PROVES
----------------
The assistant is the one part of the review surface that can call a model, fall
back to the deterministic layer, or refuse a turn. Operators still need to see
it, so each route opens exactly one span named in the module's own vocabulary
and tagged **only** with its policy-safe route template (never a concrete run,
thread, rule or user id). The two answer-producing routes additionally increment
the bounded ``claimguard_assistant_turns_total`` counter with the code's own
verification value (``accepted`` / ``repaired`` / ``fallback`` / ``refused``);
the read and status routes have no turn, so they record no outcome.

FAIL-OPEN
---------
A tracer that cannot start a span must not become a request dependency: the
routes still answer exactly as before. This file drives the real handlers over
the assistant test doubles (no database, no model, no collector), replacing only
the telemetry seam at the tracer boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final, cast

import pytest
from claimguard.ops import telemetry
from claimguard.review import app as app_module

from tests.ai import test_assistant_api as _assistant_api
from tests.ai.test_assistant_api import FLAGGED_RULE, build_app, client_for

# The assistant test doubles are pulled into this module's namespace (as
# assignments, not imports) so pytest can resolve them by name as fixtures while
# the linter still sees them as used.
assistant_store = _assistant_api.assistant_store
review_store = _assistant_api.review_store
stored_run = _assistant_api.stored_run
stub_graph = _assistant_api.stub_graph

pytestmark = pytest.mark.unit

_METRIC: Final = "claimguard_assistant_turns_total"
_OUTCOMES: Final = frozenset({"accepted", "repaired", "fallback", "refused"})


# ---------------------------------------------------------------------------
# Recording seams (no SDK, no collector)
# ---------------------------------------------------------------------------


class _Span:
    """The context manager ``span()`` enters and exits."""

    def __enter__(self) -> object:
        return object()

    def __exit__(self, *exc: object) -> bool:
        return False


class _RecordingTracer:
    """A tracer that records every span's name and attributes."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    def start_as_current_span(self, name: str, *args: object, **kwargs: object) -> _Span:
        raw = cast("Mapping[str, object]", kwargs.get("attributes") or {})
        attributes = {str(key): str(value) for key, value in raw.items()}
        self.spans.append((name, attributes))
        return _Span()


def _install_tracer(monkeypatch: pytest.MonkeyPatch, tracer: _RecordingTracer) -> None:
    """Point the real ``span`` helper at a recording tracer."""

    def _get_tracer(name: str) -> _RecordingTracer:
        return tracer

    monkeypatch.setattr(telemetry, "get_tracer", _get_tracer)


def _install_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, str]]:
    """Capture the bounded domain-metric calls the handlers make."""
    calls: list[tuple[str, str]] = []

    def record(name: str, value: str) -> None:
        calls.append((name, value))

    monkeypatch.setattr(app_module, "record_domain_metric", record)
    return calls


def _assert_no_identifiers(spans: list[tuple[str, dict[str, str]]], identifiers: list[str]) -> None:
    """No span attribute value may contain a concrete id."""
    for _name, attributes in spans:
        for key, value in attributes.items():
            for identifier in identifiers:
                assert identifier not in value, f"{key}={value!r} leaked {identifier!r}"


# ---------------------------------------------------------------------------
# Spans: one per route, route template only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ai_status_opens_one_route_template_span(
    review_store: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracer = _RecordingTracer()
    _install_tracer(monkeypatch, tracer)
    app = build_app(store=review_store)

    async with client_for(app) as client:
        response = await client.get("/v1/ai/status")

    assert response.status_code == 200, response.text
    assert tracer.spans == [("ai.status", {"route_template": "/v1/ai/status", "method": "GET"})]


@pytest.mark.asyncio
async def test_explain_records_one_turn_and_a_policy_safe_span(
    review_store: Any,
    assistant_store: Any,
    stub_graph: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _RecordingTracer()
    _install_tracer(monkeypatch, tracer)
    metrics = _install_metrics(monkeypatch)
    app = build_app(store=review_store, assistant=assistant_store)
    run_id = review_store.run.run_id

    async with client_for(app) as client:
        response = await client.post(f"/v1/runs/{run_id}/findings/{FLAGGED_RULE}/explain", json={})

    assert response.status_code == 200, response.text
    assert tracer.spans == [
        (
            "ai.explain",
            {
                "route_template": "/v1/runs/{run_id}/findings/{rule_id}/explain",
                "method": "POST",
            },
        )
    ]
    assert metrics == [(_METRIC, "fallback")]
    _assert_no_identifiers(tracer.spans, [run_id, FLAGGED_RULE])


@pytest.mark.asyncio
async def test_message_and_thread_routes_span_and_only_the_answer_records_a_turn(
    review_store: Any,
    assistant_store: Any,
    stub_graph: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _RecordingTracer()
    _install_tracer(monkeypatch, tracer)
    metrics = _install_metrics(monkeypatch)
    app = build_app(store=review_store, assistant=assistant_store)
    run_id = review_store.run.run_id

    async with client_for(app) as client:
        opened = await client.post(f"/v1/runs/{run_id}/findings/{FLAGGED_RULE}/explain", json={})
        assert opened.status_code == 200, opened.text
        thread_id = opened.json()["thread"]["thread_id"]
        # Reset the seams so each route is judged on its own contribution.
        tracer.spans.clear()
        metrics.clear()

        follow_up = await client.post(
            f"/v1/threads/{thread_id}/messages", json={"question": "what evidence?"}
        )
        assert follow_up.status_code == 200, follow_up.text
        thread = await client.get(f"/v1/threads/{thread_id}")

    assert thread.status_code == 200, thread.text
    assert tracer.spans == [
        (
            "ai.message",
            {
                "route_template": "/v1/threads/{thread_id}/messages",
                "method": "POST",
            },
        ),
        (
            "ai.thread",
            {"route_template": "/v1/threads/{thread_id}", "method": "GET"},
        ),
    ]
    # One follow-up produced exactly one assistant answer; the read produced none.
    assert metrics == [(_METRIC, "fallback")]
    _assert_no_identifiers(tracer.spans, [run_id, FLAGGED_RULE, thread_id])


@pytest.mark.asyncio
async def test_a_failed_turn_opens_its_span_but_records_no_outcome(
    review_store: Any,
    assistant_store: Any,
    stub_graph: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _RecordingTracer()
    _install_tracer(monkeypatch, tracer)
    metrics = _install_metrics(monkeypatch)
    app = build_app(store=review_store, assistant=assistant_store)
    run_id = review_store.run.run_id

    async with client_for(app) as client:
        response = await client.post(f"/v1/runs/{run_id}/findings/NOPE-99/explain", json={})

    assert response.status_code == 404, response.text
    assert [name for name, _ in tracer.spans] == ["ai.explain"]
    assert metrics == []


# ---------------------------------------------------------------------------
# Fail-open: a broken tracer changes nothing the reviewer sees
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_broken_tracer_does_not_break_the_assistant(
    review_store: Any,
    assistant_store: Any,
    stub_graph: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(name: str) -> object:
        raise RuntimeError("tracer exploded")

    monkeypatch.setattr(telemetry, "get_tracer", _boom)
    app = build_app(store=review_store, assistant=assistant_store)
    run_id = review_store.run.run_id

    async with client_for(app) as client:
        status = await client.get("/v1/ai/status")
        explain = await client.post(f"/v1/runs/{run_id}/findings/{FLAGGED_RULE}/explain", json={})

    assert status.status_code == 200, status.text
    assert explain.status_code == 200, explain.text


# ---------------------------------------------------------------------------
# The label space is closed in code (defence in depth)
# ---------------------------------------------------------------------------


def test_the_assistant_counter_is_bounded_to_the_four_verifications() -> None:
    """The counter can only ever carry the assistant's own vocabulary."""
    spec = telemetry._DOMAIN_COUNTERS.get(_METRIC)  # pyright: ignore[reportPrivateUsage]
    assert spec is not None
    label, allowed = spec
    assert label == "outcome"
    assert allowed == _OUTCOMES

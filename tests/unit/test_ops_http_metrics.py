"""P1 HTTP metrics middleware — bounded labels, template-only routes.

The middleware must label requests with the matched route TEMPLATE (or the
literal ``unmatched``), classify status codes, and never let a recorder fault or
a concrete identifier disturb the response or leak into a label.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import httpx
import pytest
from claimguard.ops.http_metrics import HttpMetricsMiddleware, status_class
from claimguard.ops.telemetry_policy import METRIC_LABEL_ALLOWLIST
from fastapi import FastAPI

_CONCRETE_PATH = "/v1/runs/CLM-0042"
_UNMATCHED_PATH = "/definitely-not-a-route/CLM-0042"


@dataclass
class _Call:
    """One recorded request: its label set and its duration."""

    labels: dict[str, str]
    duration_ms: float


class _Recorder:
    """Captures the label set the middleware would have emitted."""

    def __init__(self) -> None:
        self.calls: list[_Call] = []

    def __call__(
        self,
        *,
        method: str,
        route_template: str,
        status_class: str,
        duration_ms: float,
        service: str = "claimguard",
        component: str = "api",
    ) -> None:
        self.calls.append(
            _Call(
                labels={
                    "method": method,
                    "route_template": route_template,
                    "status_class": status_class,
                    "service": service,
                    "component": component,
                },
                duration_ms=duration_ms,
            )
        )


def _get_run(run_id: str) -> dict[str, str]:
    return {"run_id": run_id}


def _boom_recorder(**kwargs: object) -> None:
    raise RuntimeError("recorder is down")


def _build_app(recorder: Callable[..., None]) -> FastAPI:
    app = FastAPI()
    app.add_middleware(HttpMetricsMiddleware, recorder=recorder)
    app.add_api_route("/v1/runs/{run_id}", _get_run, methods=["GET"])
    return app


async def _get(app: FastAPI, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://review.test") as client:
        return await client.get(path)


async def test_matched_route_records_the_template() -> None:
    recorder = _Recorder()
    assert (await _get(_build_app(recorder), _CONCRETE_PATH)).status_code == 200
    assert recorder.calls[-1].labels["route_template"] == "/v1/runs/{run_id}"


async def test_unmatched_route_records_unmatched() -> None:
    recorder = _Recorder()
    assert (await _get(_build_app(recorder), _UNMATCHED_PATH)).status_code == 404
    assert recorder.calls[-1].labels["route_template"] == "unmatched"


async def test_concrete_identifier_never_becomes_a_label() -> None:
    recorder = _Recorder()
    app = _build_app(recorder)
    await _get(app, _CONCRETE_PATH)
    await _get(app, _UNMATCHED_PATH)
    for call in recorder.calls:
        assert call.labels["route_template"] in {"/v1/runs/{run_id}", "unmatched"}
        assert all("CLM-0042" not in value for value in call.labels.values())


@pytest.mark.parametrize(
    ("code", "expected"),
    [(200, "2xx"), (404, "4xx"), (503, "5xx"), (302, "3xx"), (100, "1xx")],
)
def test_status_class_maps_concrete_codes(code: int, expected: str) -> None:
    assert status_class(code) == expected


async def test_recorder_failure_does_not_break_the_response() -> None:
    assert (await _get(_build_app(_boom_recorder), _CONCRETE_PATH)).status_code == 200


async def test_recorded_label_keys_are_all_allowlisted() -> None:
    recorder = _Recorder()
    await _get(_build_app(recorder), _CONCRETE_PATH)
    for key in recorder.calls[-1].labels:
        assert key in METRIC_LABEL_ALLOWLIST

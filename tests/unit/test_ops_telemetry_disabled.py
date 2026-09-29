"""P1 telemetry — off by default (docs/20 §13.6).

Guarantees when no operator opts in:
1. ``telemetry_enabled`` / ``init_telemetry`` / ``telemetry_initialized`` are all
   False and no middleware is added.
2. No network connection is attempted on any disabled code path.
3. Metric recording is a silent no-op and shutdown is safe.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

import pytest
from claimguard.ops import telemetry
from claimguard.ops.telemetry import (
    init_telemetry,
    install_telemetry,
    record_http_metric,
    shutdown_telemetry,
    telemetry_enabled,
    telemetry_initialized,
)
from fastapi import FastAPI


@pytest.fixture(autouse=True)
def _isolated(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Start from an unset switch and an uninitialized module, every test."""
    monkeypatch.delenv(telemetry.OTEL_ENABLED_ENV, raising=False)
    shutdown_telemetry()
    yield
    shutdown_telemetry()


def test_telemetry_is_disabled_by_default() -> None:
    assert telemetry_enabled() is False
    assert init_telemetry() is False
    assert telemetry_initialized() is False


def test_install_telemetry_adds_no_middleware_when_disabled() -> None:
    app = FastAPI()
    before = list(app.user_middleware)
    assert install_telemetry(app) is False
    assert list(app.user_middleware) == before


def test_disabled_path_makes_no_network_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[Any] = []

    def _forbidden_connect(self: Any, address: Any) -> None:
        attempts.append(address)
        raise AssertionError("network connect attempted while telemetry is disabled")

    monkeypatch.setattr("socket.socket.connect", _forbidden_connect)
    assert telemetry_enabled() is False
    assert init_telemetry() is False
    assert install_telemetry(FastAPI()) is False
    assert attempts == []


def test_record_http_metric_is_a_silent_noop_when_disabled() -> None:
    record_http_metric(
        method="GET",
        route_template="/v1/runs/{run_id}",
        status_class="2xx",
        duration_ms=12.5,
    )


def test_shutdown_when_never_initialized_does_not_raise() -> None:
    shutdown_telemetry()
    shutdown_telemetry()

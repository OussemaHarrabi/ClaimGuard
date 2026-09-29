"""P1 telemetry — fail-open under a broken exporter (docs/obs_trace.tex §5).

Telemetry must never become a request dependency: an exporter that raises on
``export`` still yields a 200, shutdown never raises, and a malformed endpoint
turns initialization off rather than blowing up.
"""

from __future__ import annotations

from collections.abc import Generator

import httpx
import pytest
from claimguard.config import Settings
from claimguard.ops import telemetry
from claimguard.ops.telemetry import init_telemetry, install_telemetry, shutdown_telemetry
from fastapi import FastAPI

_SPAN_EXPORTER_PATH = "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter"


class _BoomExporter:
    """Stand-in OTLP span exporter whose ``export`` always raises."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def export(self, spans: object) -> None:
        raise RuntimeError("collector is dead")

    def shutdown(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _isolated(  # pyright: ignore[reportUnusedFunction]
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    monkeypatch.delenv(telemetry.OTEL_ENABLED_ENV, raising=False)
    shutdown_telemetry()
    yield
    shutdown_telemetry()


def _enabled_settings() -> Settings:
    return Settings(ops_otel_enabled=True)


def _ping() -> dict[str, str]:
    return {"status": "ok"}


async def test_exporter_failure_does_not_break_a_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(telemetry.OTEL_ENABLED_ENV, "true")
    monkeypatch.setattr(_SPAN_EXPORTER_PATH, _BoomExporter)

    app = FastAPI()
    app.add_api_route("/ping", _ping, methods=["GET"])

    assert install_telemetry(app) is True

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://review.test") as client:
        response = await client.get("/ping")
    assert response.status_code == 200


def test_shutdown_survives_exporter_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(telemetry.OTEL_ENABLED_ENV, "true")
    monkeypatch.setattr(_SPAN_EXPORTER_PATH, _BoomExporter)

    assert init_telemetry(_enabled_settings()) is True
    shutdown_telemetry()


def test_malformed_endpoint_returns_false() -> None:
    assert init_telemetry(Settings(ops_otel_enabled=True, otel_endpoint="not-a-url")) is False

"""Real-time operations stream for the Technical Reviewer console (Phase P2).

WHY THIS EXISTS
---------------
The console's four REST endpoints answer "what is the platform doing right now",
but a browser that wants to stay current has to poll them. This module adds one
WebSocket, ``WS /v1/operations/stream``, that pushes the exact same payloads when
(and only when) they change, so the console stops re-asking.

THE BOUNDARY THIS MODULE KEEPS
------------------------------
*   **Backend-only telemetry.** The stream calls the same payload builders as the
    REST surface (:mod:`claimguard.ops.operations`); it introduces no new source,
    no new credential and no new projection. A dead source degrades the stream
    exactly as it degrades REST (fail-open, source marked ``unavailable``).
*   **Same authorization as HTTP.** A WebSocket handshake does not pass through
    the HTTP middleware, so this module authenticates from the same
    ``claimguard_session`` cookie and the same signer. The resolution helper is
    shared with the middleware (:func:`resolve_session_principal`), so the two
    cannot drift. Nothing is sent before authorization succeeds.
*   **Review, don't adjudicate.** The stream carries counts, durations, trace
    identifiers, component states and the audit verdict — never a claim, a
    patient identifier or reviewer free text.
*   **Additive.** The four REST endpoints, their contracts, bounds, cache and
    fail-open behaviour are untouched.

CLOSE CODES
-----------
A rejection is a WebSocket close with an application code, never a data frame:
``4401`` when there is no valid clinic session, ``4403`` when the session is
valid but its role lacks :data:`claimguard.clinic.access.Action.READ_OPERATIONS`.
The connection is accepted first so the code reaches the client: a close sent
before accept is an HTTP handshake rejection, which loses the code.

CHANGE DETECTION
----------------
The handler sends a snapshot immediately, then polls the payload every
``ops_stream_interval_seconds`` (~3s), fingerprints its JSON and sends a new
snapshot only when the fingerprint changes. When nothing changed for
:data:`STREAM_HEARTBEAT_SECONDS` (~15s) it sends ``{"type": "ping"}`` so an idle
connection is not mistaken for a dead one. The synchronous source probes run in a
worker thread, so a slow Prometheus or Tempo cannot stall the event loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal, Protocol, cast

from fastapi import APIRouter, FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect

from claimguard.clinic.access import Action, Principal, Role, authorize
from claimguard.clinic.session import AuthenticationError, SessionSigner
from claimguard.config import get_settings
from claimguard.ops.operations import (
    AuditResponse,
    MetricsResponse,
    OverviewResponse,
    TracesResponse,
    Window,
    build_audit,
    build_metrics,
    build_overview,
    build_traces,
)

#: Default cadence at which the handler re-fingerprints a payload, in seconds.
STREAM_POLL_INTERVAL_SECONDS: Final = 3.0

#: How long a connection may go without a frame before a heartbeat is sent.
STREAM_HEARTBEAT_SECONDS: Final = 15.0

#: The trace page size the stream requests, matching the REST endpoint default.
TRACE_PAGE_LIMIT: Final = 20

#: The sections the stream can watch, and the default.
Section = Literal["overview", "metrics", "traces", "audit"]
DEFAULT_SECTION: Final[Section] = "overview"
DEFAULT_WINDOW: Final[Window] = "15m"

#: Application close codes (never sent as data).
WS_UNAUTHENTICATED: Final = 4401
WS_FORBIDDEN: Final = 4403

#: ``app.state`` override attributes, injectable so tests never wait ~3s.
_STREAM_INTERVAL_ATTR: Final = "ops_stream_interval_seconds"
_STREAM_HEARTBEAT_ATTR: Final = "ops_stream_heartbeat_seconds"

_SECTIONS: Final[frozenset[str]] = frozenset({"overview", "metrics", "traces", "audit"})
_WINDOWS: Final[frozenset[str]] = frozenset({"5m", "15m", "1h"})

_Payload = OverviewResponse | MetricsResponse | TracesResponse | AuditResponse


class ClinicMembershipSource(Protocol):
    """The one method session resolution needs from the clinic directory."""

    def membership(self, user_id: str, tenant_id: str) -> Role | None:
        """Return the current role for an active membership, or None."""
        ...


class SessionUnavailable(Exception):  # noqa: N818 - the name reads as the failure
    """The deployment has no clinic session signer configured."""


class SessionMissing(AuthenticationError):  # noqa: N818 - the name reads as the failure
    """A protected request carried no clinic session cookie.

    A distinct type so the HTTP middleware can keep answering the exact
    "sign-in required" body it always has, while the WebSocket maps every
    authentication failure to one close code.
    """


def resolve_session_principal(
    *,
    signer: SessionSigner | None,
    directory: ClinicMembershipSource | None,
    token: str | None,
) -> Principal:
    """Resolve a clinic principal from a session cookie, the HTTP way.

    Shared by the HTTP middleware and the WebSocket stream so the two cannot
    drift. Raises :class:`SessionUnavailable` when the deployment has no signer,
    :class:`SessionMissing` when no cookie was sent, and
    :class:`AuthenticationError` when the cookie is invalid — each caller maps
    those to its own transport's rejection.
    """
    if signer is None:
        raise SessionUnavailable("clinic session key is not configured")
    if not token:
        raise SessionMissing("clinic sign-in required")
    if directory is None:
        raise AuthenticationError("clinic session is invalid")
    return signer.resolve(token, membership=directory.membership)


router = APIRouter(prefix="/v1/operations", tags=["operations"])


@dataclass(slots=True)
class _Subscription:
    """What one connection is watching, and the state change detection needs."""

    section: Section
    window: Window
    fingerprint: str | None = None
    last_sent: float = 0.0


@router.websocket("/stream")
async def operations_stream(websocket: WebSocket) -> None:
    """Push operations payloads, authorized exactly like the REST surface."""
    app = cast(FastAPI, websocket.app)
    if not await _authorize(websocket, app):
        return
    await websocket.accept()
    subscription = _Subscription(*_initial_subscription(websocket))
    lock = asyncio.Lock()
    await _maybe_send_snapshot(websocket, app, subscription, lock, force=True)
    sender = asyncio.create_task(_poll_for_changes(websocket, app, subscription, lock))
    try:
        await _receive_switches(websocket, app, subscription, lock)
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect):
            await sender


async def _authorize(websocket: WebSocket, app: FastAPI) -> bool:
    """Resolve and authorize the session; close with 4401/4403 on rejection.

    The connection is accepted before the close so the application code survives
    the handshake: a close sent first is an HTTP rejection that drops the code.
    """
    try:
        principal = resolve_session_principal(
            signer=getattr(app.state, "signer", None),
            directory=getattr(app.state, "directory", None),
            token=websocket.cookies.get("claimguard_session"),
        )
    except (SessionUnavailable, AuthenticationError):
        await websocket.accept()
        await websocket.close(code=WS_UNAUTHENTICATED)
        return False
    try:
        authorize(principal, Action.READ_OPERATIONS, tenant_id=principal.tenant_id)
    except PermissionError:
        await websocket.accept()
        await websocket.close(code=WS_FORBIDDEN)
        return False
    return True


async def _receive_switches(
    websocket: WebSocket,
    app: FastAPI,
    subscription: _Subscription,
    lock: asyncio.Lock,
) -> None:
    """Apply client switch messages until the connection drops.

    A malformed or partial frame is ignored rather than treated as a disconnect:
    only a real :class:`WebSocketDisconnect` ends the stream.
    """
    while True:
        try:
            message = await websocket.receive_json()
        except (json.JSONDecodeError, KeyError):
            continue
        if _apply_switch(subscription, message):
            await _maybe_send_snapshot(websocket, app, subscription, lock, force=False)


async def _poll_for_changes(
    websocket: WebSocket,
    app: FastAPI,
    subscription: _Subscription,
    lock: asyncio.Lock,
) -> None:
    """Send a snapshot on change, or a heartbeat when nothing changed."""
    interval = _poll_interval(app)
    heartbeat = _heartbeat_interval(app)
    while True:
        await asyncio.sleep(interval)
        async with lock:
            payload = await _build_payload(app, subscription)
            fingerprint = _fingerprint(payload)
            now = time.monotonic()
            if fingerprint != subscription.fingerprint:
                await _send_snapshot(websocket, subscription, payload, fingerprint)
            elif now - subscription.last_sent >= heartbeat:
                await websocket.send_json({"type": "ping", "at": _utc_now()})
                subscription.last_sent = now


async def _maybe_send_snapshot(
    websocket: WebSocket,
    app: FastAPI,
    subscription: _Subscription,
    lock: asyncio.Lock,
    *,
    force: bool,
) -> None:
    """Send the current payload when it changed (or when forced on connect)."""
    async with lock:
        payload = await _build_payload(app, subscription)
        fingerprint = _fingerprint(payload)
        if force or fingerprint != subscription.fingerprint:
            await _send_snapshot(websocket, subscription, payload, fingerprint)


async def _send_snapshot(
    websocket: WebSocket,
    subscription: _Subscription,
    payload: _Payload,
    fingerprint: str,
) -> None:
    """Serialise one snapshot frame and remember what the client now holds."""
    await websocket.send_json(
        {
            "type": "snapshot",
            "section": subscription.section,
            "at": _utc_now(),
            "payload": payload.model_dump(mode="json"),
        }
    )
    subscription.fingerprint = fingerprint
    subscription.last_sent = time.monotonic()


async def _build_payload(app: FastAPI, subscription: _Subscription) -> _Payload:
    """Build the payload off the event loop: the source probes are synchronous."""
    return await asyncio.to_thread(_payload_for, app, subscription.section, subscription.window)


def _payload_for(app: FastAPI, section: Section, window: Window) -> _Payload:
    """Build a FRESH payload; the stream must not read its own change signal from a cache.

    The REST cache holds entries for ~5s while this loop re-checks every ~3s, so
    serving the stream from that cache would both delay a real change and mask it
    entirely for as long as the entry lived. Change detection has to see the
    current truth, so these builders are called directly.
    """
    if section == "overview":
        return build_overview(app)
    if section == "metrics":
        return build_metrics(app, window)
    if section == "traces":
        return build_traces(app, TRACE_PAGE_LIMIT)
    return build_audit(app)


def _initial_subscription(websocket: WebSocket) -> tuple[Section, Window]:
    """Read the frozen query contract, falling back to the defaults on bad input."""
    params: Mapping[str, str] = websocket.query_params
    section = params.get("section", DEFAULT_SECTION)
    window = params.get("window", DEFAULT_WINDOW)
    resolved_section: Section = cast(Section, section) if section in _SECTIONS else DEFAULT_SECTION
    resolved_window: Window = cast(Window, window) if window in _WINDOWS else DEFAULT_WINDOW
    return resolved_section, resolved_window


def _apply_switch(subscription: _Subscription, message: object) -> bool:
    """Apply a ``{"section", "window"}`` message; True when something changed."""
    if not isinstance(message, dict):
        return False
    frame = cast("dict[str, object]", message)
    applied = False
    section = frame.get("section")
    if isinstance(section, str) and section in _SECTIONS and section != subscription.section:
        subscription.section = cast(Section, section)
        applied = True
    window = frame.get("window")
    if isinstance(window, str) and window in _WINDOWS and window != subscription.window:
        subscription.window = cast(Window, window)
        applied = True
    return applied


#: Fields stamped fresh on every build rather than describing the platform's
#: state. They must not take part in change detection: including them would make
#: every poll look like a change and turn the stream into a firehose of
#: identical snapshots every few seconds.
_VOLATILE_KEYS: Final = frozenset({"checked_at"})


def _fingerprint(payload: _Payload) -> str:
    """A fingerprint of the payload's STATE, ignoring per-build metadata."""
    stable = {
        key: value
        for key, value in payload.model_dump(mode="json").items()
        if key not in _VOLATILE_KEYS
    }
    return json.dumps(stable, sort_keys=True, default=str)


def _utc_now() -> str:
    """The ISO-8601 UTC timestamp every frame carries."""
    return datetime.now(UTC).isoformat()


def _poll_interval(app: FastAPI) -> float:
    """The change-detection cadence: an injected override, else configuration."""
    override = _positive_float(getattr(app.state, _STREAM_INTERVAL_ATTR, None))
    if override is not None:
        return override
    try:
        configured = _positive_float(get_settings().ops_stream_interval_seconds)
    except Exception:  # noqa: BLE001 - a broken config must not stop the stream
        return STREAM_POLL_INTERVAL_SECONDS
    return configured if configured is not None else STREAM_POLL_INTERVAL_SECONDS


def _heartbeat_interval(app: FastAPI) -> float:
    """The idle cadence: an injected override, else the module default."""
    override = _positive_float(getattr(app.state, _STREAM_HEARTBEAT_ATTR, None))
    return override if override is not None else STREAM_HEARTBEAT_SECONDS


def _positive_float(value: object) -> float | None:
    """Return ``value`` as a positive finite float, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    resolved = float(value)
    return resolved if math.isfinite(resolved) and resolved > 0 else None


__all__ = [
    "ClinicMembershipSource",
    "SessionMissing",
    "SessionUnavailable",
    "resolve_session_principal",
    "router",
]

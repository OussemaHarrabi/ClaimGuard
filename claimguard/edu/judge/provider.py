"""The judge transport seam: a provider, a default, and a real one.

Three pieces, in the order they matter:

*   :class:`JudgeProvider` — the seam. ``assess(state, questions)`` and
    ``list_models()`` are the only two operations this layer ever needs, and a
    provider MUST raise :class:`JudgeError` for *every* failure. That is what
    makes the safety boundary enforceable: the caller has exactly one exception
    family to make inert.
*   :class:`NullJudge` — the default. It performs no I/O at all, so with no key
    configured the judge is a no-op that cannot even accidentally dial out.
*   :class:`JevJudge` — the real one, built on an **injectable** transport
    callable. Tests inject a fake and the network is never touched; production
    injects nothing and the standard library is used.

Failure modes are typed, never generic: :class:`JudgeDisabledError`,
:class:`JudgeTransportError` (no HTTP response: DNS, refused, timeout),
:class:`JudgeHTTPError` (a response, with a non-2xx status) and
:class:`JudgeResponseError` (a 2xx response whose body is not the contract).
Every message is passed through :meth:`~claimguard.edu.judge.config.JudgeSettings.redact`
before it is raised, so a credential cannot escape into a log.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol, TypeVar, cast, runtime_checkable

from pydantic import BaseModel, ValidationError

from claimguard.edu.judge.config import JudgeSettings
from claimguard.edu.judge.models import (
    PATH_MODELS,
    PATH_SYSTEMONE,
    ModelInfo,
    ModelsResponse,
    Question,
    SystemOneRequest,
    SystemOneResponse,
)

#: How much of an error body is quoted back to the operator (it is vendor text, not ours).
ERROR_BODY_CHARS: Final = 400

ModelT = TypeVar("ModelT", bound=BaseModel)


class JudgeError(RuntimeError):
    """The judge could not produce a usable answer. Every failure mode derives from this."""


class JudgeDisabledError(JudgeError):
    """No API key is configured, so the judge must not run at all."""


class JudgeTransportError(JudgeError):
    """The request never produced an HTTP response (DNS, refused connection, timeout)."""


class JudgeHTTPError(JudgeError):
    """The endpoint answered with a non-2xx status."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"judge endpoint returned HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class JudgeResponseError(JudgeError):
    """A 2xx body that does not match the contract: non-JSON, wrong shape, unknown type."""


# ---------------------------------------------------------------------------
# The transport seam
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HttpRequest:
    """One HTTP request, fully described — what a fake transport records and asserts on."""

    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout: float

    def payload(self) -> dict[str, Any]:
        """The JSON body as a mapping (``{}`` when there is none)."""
        if not self.body:
            return {}
        return cast("dict[str, Any]", json.loads(self.body))


@runtime_checkable
class JudgeTransport(Protocol):
    """The one HTTP operation the provider needs. Injectable so tests never dial out."""

    def __call__(self, request: HttpRequest) -> str:
        """Perform ``request`` and return the response body text."""
        ...


def default_transport(request: HttpRequest) -> str:
    """Send ``request`` with the standard library, mapping failures to typed errors.

    No third-party HTTP client: this layer's only dependency is ``urllib``. The
    endpoint is operator-configured, so the ``S310`` audit warning is expected
    and deliberate — the URL can never come from claim data.
    """
    http_request = urllib.request.Request(  # noqa: S310 - operator-configured endpoint
        request.url, data=request.body, headers=dict(request.headers), method=request.method
    )
    try:
        with urllib.request.urlopen(http_request, timeout=request.timeout) as response:  # noqa: S310
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise JudgeHTTPError(exc.code, _error_detail(exc)) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise JudgeTransportError(f"judge endpoint unreachable: {exc}") from exc


def _error_detail(exc: urllib.error.HTTPError) -> str:
    """A bounded excerpt of an error response body (a 422 carries the validation detail)."""
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except (OSError, ValueError):  # pragma: no cover - a body that cannot be read at all
        return "<unreadable error body>"
    return raw[:ERROR_BODY_CHARS].strip() or "<empty error body>"


def _parse(model: type[ModelT], raw: str, settings: JudgeSettings, what: str) -> ModelT:
    """Validate a response body strictly, or raise :class:`JudgeResponseError`."""
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise JudgeResponseError(
            settings.redact(f"{what} is not JSON: {exc.msg} at offset {exc.pos}")
        ) from exc
    try:
        return model.model_validate(parsed)
    except ValidationError as exc:
        raise JudgeResponseError(
            settings.redact(f"{what} does not match the contract: {_first_error(exc)}")
        ) from exc


def _first_error(exc: ValidationError) -> str:
    """The first validation error as ``location: message`` — enough to diagnose, not to log."""
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first["loc"]) or "<root>"
    return f"{location}: {first['msg']}"


def _redacted_error(settings: JudgeSettings, exc: JudgeError) -> JudgeError:
    """Rebuild a provider error after credential redaction, preserving its type."""
    if isinstance(exc, JudgeHTTPError):
        return JudgeHTTPError(exc.status_code, settings.redact(exc.detail))
    message = settings.redact(str(exc))
    if isinstance(exc, JudgeDisabledError):
        return JudgeDisabledError(message)
    if isinstance(exc, JudgeTransportError):
        return JudgeTransportError(message)
    if isinstance(exc, JudgeResponseError):
        return JudgeResponseError(message)
    return JudgeError(message)


# ---------------------------------------------------------------------------
# The provider seam
# ---------------------------------------------------------------------------


@runtime_checkable
class JudgeProvider(Protocol):
    """The judge-neutral seam. Implementations MUST raise :class:`JudgeError` on failure."""

    name: str

    def assess(self, state: Any, questions: Mapping[str, Question]) -> SystemOneResponse:
        """Ask ``questions`` about ``state`` and return the typed answers."""
        ...

    def list_models(self) -> list[str]:
        """The model names this credential can actually use."""
        ...


class NullJudge:
    """The default provider: no configuration, no network, no assessment.

    It exists so that "no key" is a *state*, not a branch scattered through the
    callers: the runner asks it exactly as it would ask the real provider and
    records the refusal as ``skipped``.
    """

    name: str = "null"

    def __init__(self, reason: str = "judge disabled: no API key configured") -> None:
        self.reason = reason

    def assess(self, state: Any, questions: Mapping[str, Question]) -> SystemOneResponse:
        """Refuse — without inspecting ``state`` and without any I/O."""
        raise JudgeDisabledError(self.reason)

    def list_models(self) -> list[str]:
        """No credential, therefore no models."""
        return []


# ---------------------------------------------------------------------------
# The Jev provider
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeReport:
    """What ``GET /v1/models`` said — access proof plus the real model name."""

    url: str
    models: tuple[ModelInfo, ...]
    configured_model: str

    @property
    def configured_model_offered(self) -> bool:
        """Whether the configured model name is one the credential can actually use."""
        return any(model.name == self.configured_model for model in self.models)

    def names(self) -> list[str]:
        """The offered model names, in the order the vendor listed them."""
        return [model.name for model in self.models]


class JevJudge:
    """TypeSafe Jev ("System One"): typed probabilistic decisions over our state.

    The provider never builds prose and never interprets an answer beyond the
    contract: it posts the state and the questions, and returns exactly what came
    back. Everything a human reads is derived afterwards, in
    :mod:`claimguard.edu.judge.run`, and lands in the sidecar.
    """

    name: str = "jev"

    def __init__(self, settings: JudgeSettings, *, transport: JudgeTransport | None = None) -> None:
        self.settings = settings
        self._transport: JudgeTransport = default_transport if transport is None else transport

    # -- requests -----------------------------------------------------------

    def build_envelope(self, state: Any, questions: Mapping[str, Question]) -> SystemOneRequest:
        """Validate one request against the contract *before* anything is sent."""
        return SystemOneRequest(model=self.settings.model, state=state, questions=dict(questions))

    def build_request(self, state: Any, questions: Mapping[str, Question]) -> HttpRequest:
        """Build the exact ``POST /v1/systemone`` request (URL, headers, body)."""
        payload = self.build_envelope(state, questions).model_dump(mode="json")
        return HttpRequest(
            method="POST",
            url=self.settings.endpoint(PATH_SYSTEMONE),
            headers=self.settings.headers(json_body=True),
            body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            timeout=self.settings.timeout,
        )

    def build_models_request(self) -> HttpRequest:
        """Build the ``GET /v1/models`` request — the only call that needs no body."""
        return HttpRequest(
            method="GET",
            url=self.settings.endpoint(PATH_MODELS),
            headers=self.settings.headers(json_body=False),
            body=None,
            timeout=self.settings.timeout,
        )

    # -- the two provider operations ----------------------------------------

    def assess(self, state: Any, questions: Mapping[str, Question]) -> SystemOneResponse:
        """Ask Jev ``questions`` about ``state``; raise :class:`JudgeError` on any fault."""
        request = self.build_request(state, questions)
        raw = self._send(request)
        return _parse(SystemOneResponse, raw, self.settings, "systemone response")

    def list_models(self) -> list[str]:
        """The model names this credential can use (``GET /v1/models``)."""
        return [model.name for model in self._fetch_models()]

    # -- probe --------------------------------------------------------------

    def probe(self) -> ProbeReport:
        """Verify access and discover the real model name in one call.

        This is the first thing to run when the key arrives: it proves the
        credential works and shows which model names actually exist, so the
        ``CLAIMGUARD_JEV_MODEL`` default can be replaced with a real one instead
        of being trusted.
        """
        models = self._fetch_models()
        return ProbeReport(
            url=self.settings.endpoint(PATH_MODELS),
            models=tuple(models),
            configured_model=self.settings.model,
        )

    def _fetch_models(self) -> list[ModelInfo]:
        raw = self._send(self.build_models_request())
        return _parse(ModelsResponse, raw, self.settings, "models response").models

    # -- transport ----------------------------------------------------------

    def _send(self, request: HttpRequest) -> str:
        """Perform one request through the injected transport, keeping errors typed."""
        try:
            return self._transport(request)
        except JudgeError as exc:
            raise _redacted_error(self.settings, exc) from exc
        except (OSError, ValueError) as exc:
            raise JudgeTransportError(
                self.settings.redact(f"judge transport failed: {exc}")
            ) from exc


def build_provider(
    settings: JudgeSettings, *, transport: JudgeTransport | None = None
) -> JudgeProvider:
    """The provider the settings describe: the real one when a key exists, else the null one.

    This is the only place that decides which provider runs, so "no key means no
    network" is a property of the construction, not of every call site.
    """
    if not settings.configured():
        return NullJudge()
    return JevJudge(settings, transport=transport)

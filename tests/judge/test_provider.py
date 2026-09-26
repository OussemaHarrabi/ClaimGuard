"""The provider: the exact request, the strict parse, and every failure mode typed.

The transport is injected everywhere, so no test in this file can reach the
network. The standard library's own mapping is exercised separately, by patching
``urlopen`` itself — that is the code path production uses.
"""

from __future__ import annotations

import io
import urllib.error
from email.message import Message
from typing import Any

import pytest
from claimguard.edu.judge import provider
from claimguard.edu.judge.models import ChoiceAnswer, NoulAnswer, ScoreAnswer
from claimguard.edu.judge.provider import (
    HttpRequest,
    JevJudge,
    JudgeDisabledError,
    JudgeHTTPError,
    JudgeResponseError,
    JudgeTransportError,
    NullJudge,
    build_provider,
    default_transport,
)
from pydantic import ValidationError

from tests.judge import (
    API_KEY,
    BASE_URL,
    MODEL,
    FakeTransport,
    models_body,
    settings,
    systemone_body,
)

STATE: dict[str, Any] = {"finding": {"claim_id": "CG-1"}, "evidence": [], "rule_excerpt": {}}


def questions() -> dict[str, Any]:
    """A minimal but contract-valid question set."""
    return {
        "grounded": {"type": "noul", "instructions": "grounded?"},
        "status_agreement": {"type": "choice", "criteria": {"agree": "yes", "disagree": "no"}},
        "attention": {"type": "score", "criteria": ["can wait", "today"]},
    }


def judge(transport: FakeTransport, **overrides: str) -> JevJudge:
    """A real provider wired to a fake transport."""
    return JevJudge(settings(**overrides), transport=transport)


class FakeResponse:
    """The context-manager response object ``urlopen`` yields."""

    def __init__(self, body: str) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------


def test_the_systemone_request_is_exactly_the_documented_shape() -> None:
    transport = FakeTransport(body=systemone_body())
    request = judge(transport).build_request(STATE, questions())
    assert request.method == "POST"
    assert request.url == f"{BASE_URL}/v1/systemone"
    assert request.headers["Authorization"] == f"Bearer {API_KEY}"
    assert request.headers["Content-Type"] == "application/json"
    assert request.timeout == 5
    assert set(request.payload()) == {"model", "state", "questions"}
    assert request.payload()["model"] == MODEL
    assert set(request.payload()["questions"]) == set(questions())


def test_the_model_list_request_is_a_get_with_no_body() -> None:
    request = judge(FakeTransport()).build_models_request()
    assert request.method == "GET"
    assert request.url == f"{BASE_URL}/v1/models"
    assert request.body is None
    assert "Content-Type" not in request.headers


def test_no_key_means_no_authorization_header_at_all() -> None:
    request = judge(FakeTransport(), CLAIMGUARD_TYPESAFE_API_KEY="").build_models_request()
    assert "Authorization" not in request.headers


def test_an_invalid_question_set_is_refused_before_anything_is_sent() -> None:
    transport = FakeTransport(body=systemone_body())
    with pytest.raises(ValidationError):
        judge(transport).assess(STATE, {})
    assert not transport.called


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_each_answer_variant_parses_into_the_typed_model() -> None:
    transport = FakeTransport(body=systemone_body())
    response = judge(transport).assess(STATE, questions())
    assert isinstance(response.answer_for("grounded"), NoulAnswer)
    assert isinstance(response.answer_for("status_agreement"), ChoiceAnswer)
    assert isinstance(response.answer_for("attention"), ScoreAnswer)
    assert response.model == MODEL
    assert response.usage.input_tokens == 512


def test_a_non_json_body_is_a_response_error() -> None:
    with pytest.raises(JudgeResponseError, match="not JSON"):
        judge(FakeTransport(body="<html>gateway</html>")).assess(STATE, questions())


def test_an_unknown_answer_type_is_a_response_error() -> None:
    body = systemone_body(answers={"grounded": {"type": "ranking", "order": ["a"]}})
    with pytest.raises(JudgeResponseError, match="does not match the contract"):
        judge(FakeTransport(body=body)).assess(STATE, questions())


def test_a_response_without_usage_is_a_response_error() -> None:
    body = systemone_body()
    with pytest.raises(JudgeResponseError, match="usage"):
        judge(FakeTransport(body=body.replace('"usage"', '"token_usage"'))).assess(
            STATE, questions()
        )


def test_a_models_body_that_is_not_the_contract_is_a_response_error() -> None:
    with pytest.raises(JudgeResponseError):
        judge(FakeTransport(body='{"models": [{"name": "x", "extra": 1}]}')).list_models()


# ---------------------------------------------------------------------------
# The standard library transport, and its error mapping
# ---------------------------------------------------------------------------


def test_the_default_transport_returns_the_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def opener(*args: Any, **kwargs: Any) -> FakeResponse:
        return FakeResponse(systemone_body())

    monkeypatch.setattr(provider.urllib.request, "urlopen", opener)
    request = HttpRequest("POST", f"{BASE_URL}/v1/systemone", {}, b"{}", 5.0)
    assert default_transport(request) == systemone_body()


@pytest.mark.parametrize(
    ("status", "detail"),
    [(422, "Unprocessable Entity"), (500, "Internal Server Error")],
)
def test_an_http_error_becomes_a_typed_error_carrying_its_status(
    monkeypatch: pytest.MonkeyPatch, status: int, detail: str
) -> None:
    def raise_http_error(*args: Any, **kwargs: Any) -> Any:
        raise urllib.error.HTTPError(
            f"{BASE_URL}/v1/systemone",
            status,
            detail,
            Message(),
            io.BytesIO(b'{"detail": [{"loc": ["body"], "msg": "bad", "type": "value_error"}]}'),
        )

    monkeypatch.setattr(provider.urllib.request, "urlopen", raise_http_error)
    request = HttpRequest("POST", f"{BASE_URL}/v1/systemone", {}, b"{}", 5.0)
    with pytest.raises(JudgeHTTPError) as caught:
        default_transport(request)
    assert caught.value.status_code == status
    assert '"msg": "bad"' in caught.value.detail, "the vendor's validation detail is kept"


def test_an_unreachable_endpoint_becomes_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_url_error(*args: Any, **kwargs: Any) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(provider.urllib.request, "urlopen", raise_url_error)
    request = HttpRequest("GET", f"{BASE_URL}/v1/models", {}, None, 5.0)
    with pytest.raises(JudgeTransportError, match="unreachable"):
        default_transport(request)


def test_a_timeout_becomes_a_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(*args: Any, **kwargs: Any) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr(provider.urllib.request, "urlopen", raise_timeout)
    request = HttpRequest("POST", f"{BASE_URL}/v1/systemone", {}, b"{}", 0.001)
    with pytest.raises(JudgeTransportError):
        default_transport(request)


def test_an_http_error_body_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_http_error(*args: Any, **kwargs: Any) -> Any:
        raise urllib.error.HTTPError(
            f"{BASE_URL}/v1/systemone", 500, "boom", Message(), io.BytesIO(b"x" * 5000)
        )

    monkeypatch.setattr(provider.urllib.request, "urlopen", raise_http_error)
    request = HttpRequest("POST", f"{BASE_URL}/v1/systemone", {}, b"{}", 5.0)
    with pytest.raises(JudgeHTTPError) as caught:
        default_transport(request)
    assert len(caught.value.detail) == provider.ERROR_BODY_CHARS


def test_a_transport_fault_never_echoes_the_credential() -> None:
    transport = FakeTransport(error=OSError(f"proxy rejected bearer {API_KEY}"))
    with pytest.raises(JudgeTransportError) as caught:
        judge(transport).assess(STATE, questions())
    assert API_KEY not in str(caught.value)
    assert "redacted" in str(caught.value)


def test_an_http_error_from_the_endpoint_surfaces_as_itself() -> None:
    transport = FakeTransport(error=JudgeHTTPError(422, "bad request"))
    with pytest.raises(JudgeHTTPError):
        judge(transport).assess(STATE, questions())


def test_an_http_error_body_never_echoes_the_credential() -> None:
    transport = FakeTransport(error=JudgeHTTPError(422, f"vendor echoed bearer {API_KEY}"))
    with pytest.raises(JudgeHTTPError) as caught:
        judge(transport).assess(STATE, questions())
    assert API_KEY not in str(caught.value)
    assert API_KEY not in caught.value.detail
    assert "redacted" in caught.value.detail


# ---------------------------------------------------------------------------
# The null provider and the factory
# ---------------------------------------------------------------------------


def test_the_null_judge_refuses_without_any_io() -> None:
    null = NullJudge()
    with pytest.raises(JudgeDisabledError, match="no API key"):
        null.assess(STATE, questions())
    assert null.list_models() == []
    assert null.name == "null"


def test_the_factory_follows_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(build_provider(settings(CLAIMGUARD_TYPESAFE_API_KEY="")), NullJudge)
    configured = build_provider(settings())
    assert isinstance(configured, JevJudge)
    assert configured.name == "jev"


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------


def test_probe_proves_access_and_lists_the_offered_models() -> None:
    transport = FakeTransport(body=models_body(("jev-test-1", "jev-test-2")))
    report = judge(transport).probe()
    assert report.url == f"{BASE_URL}/v1/models"
    assert report.names() == ["jev-test-1", "jev-test-2"]
    assert report.configured_model == MODEL
    assert report.configured_model_offered
    assert transport.requests[0].method == "GET"


def test_probe_flags_a_configured_model_the_credential_does_not_offer() -> None:
    transport = FakeTransport(body=models_body(("jev-2026-09",)))
    report = judge(transport, CLAIMGUARD_JEV_MODEL="jev-latest").probe()
    assert not report.configured_model_offered
    assert report.names() == ["jev-2026-09"]


def test_probe_surfaces_a_typed_failure() -> None:
    transport = FakeTransport(error=JudgeHTTPError(401, "invalid token"))
    with pytest.raises(JudgeHTTPError):
        judge(transport).probe()

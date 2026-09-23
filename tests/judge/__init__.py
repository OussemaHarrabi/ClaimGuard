"""Shared fixtures for the advisory judge tests (``tests/judge``).

Two rules hold for every test in this package:

*   **No network.** The provider takes an injectable transport, so every test
    either injects :class:`FakeTransport` or injects nothing at all and asserts
    that no request was made. The offline tests go further and replace
    ``urllib.request.urlopen`` with a bomb via :func:`forbid_network`, so a stray
    call fails the test instead of quietly succeeding.
*   **No mentor pack.** Records are produced by the real engine over the
    vendored catalogue in ``tests/edu/fixtures/pack_reference``, so these tests
    run in CI where the pack is absent.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

import pytest
from claimguard.edu.emit import serialize
from claimguard.edu.judge import provider
from claimguard.edu.judge.config import JudgeSettings
from claimguard.edu.judge.provider import HttpRequest
from claimguard.edu.policy import RuleMeta

from tests.edu import RULES_DIR, base_claim, imaging_claim, record, rules_context

#: A credential that exists only inside the test process (never a real one).
API_KEY: Final = "ts-test-key-not-a-real-credential"
BASE_URL: Final = "https://api.typesafe.test"
MODEL: Final = "jev-test-1"

#: A configured judge environment, overridable per test.
ENV: Final[Mapping[str, str]] = {
    "CLAIMGUARD_TYPESAFE_API_KEY": API_KEY,
    "CLAIMGUARD_TYPESAFE_BASE_URL": BASE_URL,
    "CLAIMGUARD_JEV_MODEL": MODEL,
    "CLAIMGUARD_JEV_TIMEOUT_SECONDS": "5",
}

#: The three choice names the second-opinion question offers.
AGREEMENT_CHOICES: Final = ("agree", "agree_but_low_confidence", "disagree")


def settings(**overrides: str) -> JudgeSettings:
    """Test settings, with individual variables overridden."""
    return JudgeSettings.from_env({**ENV, **overrides})


def rule_for(rule_id: str = "R001") -> RuleMeta:
    """One rule-manifest entry from the vendored catalogue."""
    return rules_context().rules[rule_id]


def sample(rule_id: str = "R001") -> tuple[dict[str, Any], dict[str, Any]]:
    """A real engine record and the claim envelope it describes (no pack needed)."""
    claim = base_claim()
    return record(claim, rule_id), claim


def failing() -> tuple[dict[str, Any], dict[str, Any]]:
    """A real FAIL record: an imaging line that cites no authorization (R008)."""
    claim = imaging_claim()
    claim["claim_id"] = "CG-TEST-0002"
    claim["lines"][0]["authorization_id"] = None
    return record(claim, "R008"), claim


# ---------------------------------------------------------------------------
# Response bodies
# ---------------------------------------------------------------------------


def systemone_body(
    *,
    model: str = MODEL,
    grounded: float = 0.94,
    choice: str = "agree",
    confidence: float = 0.82,
    score: float = 1.0,
    input_tokens: int = 512,
    output_tokens: int = 24,
    answers: Mapping[str, Any] | None = None,
) -> str:
    """A contract-shaped ``/v1/systemone`` body with one answer per question."""
    others = [name for name in AGREEMENT_CHOICES if name != choice]
    spread = (1.0 - confidence) / len(others)
    choice_probabilities = {name: (confidence if name == choice else spread) for name in others}
    choice_probabilities[choice] = confidence
    if answers is None:
        answers = {
            "grounded": {"type": "noul", "noul": grounded},
            "status_agreement": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": choice_probabilities,
            },
            "attention": {
                "type": "score",
                "score": score,
                "confidence": confidence,
                "legend": {
                    "0": "can wait",
                    "1": "needs attention this week",
                    "2": "needs attention today",
                },
                "probabilities": {"0": 1.0 - confidence, "1": confidence, "2": 0.0},
            },
        }
    return json.dumps(
        {
            "model": model,
            "answers": answers,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    )


def models_body(names: Sequence[str] = (MODEL,)) -> str:
    """A contract-shaped ``/v1/models`` body."""
    return json.dumps(
        {
            "models": [
                {
                    "name": name,
                    "description": f"test model {name}",
                    "release_date": "2026-09-01",
                }
                for name in names
            ]
        }
    )


@dataclass
class FakeTransport:
    """A transport that never dials out: it records requests and returns injected text."""

    body: str = ""
    error: BaseException | None = None
    requests: list[HttpRequest] = field(default_factory=list[HttpRequest])

    def __call__(self, request: HttpRequest) -> str:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.body

    @property
    def payloads(self) -> list[dict[str, Any]]:
        """The JSON body of every request made, in order."""
        return [request.payload() for request in self.requests]

    @property
    def called(self) -> bool:
        """Whether anything was sent at all."""
        return bool(self.requests)


def forbid_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the standard library's opener with a bomb; return the call log.

    A test that asserts ``calls == []`` after exercising a code path has proved
    that the path could not have used the network — not merely that it did not
    need to.
    """
    calls: list[str] = []

    def bomb(*args: Any, **kwargs: Any) -> Any:
        calls.append("urlopen")
        raise AssertionError("the judge used the network")

    monkeypatch.setattr(provider.urllib.request, "urlopen", bomb)
    return calls


# ---------------------------------------------------------------------------
# Files and CLI arguments
# ---------------------------------------------------------------------------


def write_inputs(
    directory: Path, pairs: Sequence[tuple[dict[str, Any], dict[str, Any]]]
) -> tuple[Path, Path]:
    """Write one results JSONL and one claims JSONL (both validated) under ``directory``."""
    results = directory / "results.jsonl"
    claims = directory / "claims.jsonl"
    results.write_text(
        "".join(f"{serialize(record_entry, claim)}\n" for record_entry, claim in pairs),
        encoding="utf-8",
    )
    claims.write_text(
        "".join(f"{json.dumps(claim, ensure_ascii=False)}\n" for _, claim in pairs),
        encoding="utf-8",
    )
    return results, claims


def assess_args(results: Path, claims: Path, output: Path) -> argparse.Namespace:
    """The parsed-argument shape of ``claimguard judge assess``."""
    return argparse.Namespace(
        command="judge",
        action="assess",
        results=str(results),
        claims=str(claims),
        output=str(output),
        rules_dir=str(RULES_DIR),
    )


def probe_args() -> argparse.Namespace:
    """The parsed-argument shape of ``claimguard judge probe``."""
    return argparse.Namespace(command="judge", action="probe")

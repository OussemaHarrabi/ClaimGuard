"""Typed mirror of the TypeSafe Jev ("System One") HTTP contract.

Every field name, discriminator and required/optional split below is taken from
the vendor's own ``https://api.typesafe.ai/openapi.json``; none of it is ours to
improve. Jev is a *typed* model: it never returns generated text, only a
schema-matched decision per question — a probability (``noul``), a named choice
with calibrated probabilities (``choice``), or a position on an ordered scale
(``score``). That is exactly why it can be mirrored as Pydantic models instead
of being parsed by hand.

Two rules make the mirror trustworthy:

*   ``extra="forbid"`` everywhere — a payload with an unknown field is a
    contract violation, not something to be quietly dropped. For the *request*
    that is a hard guarantee: we can never send a field the vendor did not
    document. For a *response* it means a vendor-side addition fails loudly and
    the assessment is recorded as ``failed`` (inert), never mis-read.
*   ``state`` and ``instructions`` accept any JSON value (the vendor's
    ``string | object | array``) but are validated for JSON-serializability, so
    a non-JSON object cannot reach the wire.

This module is pure data: no I/O, no configuration, no network.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Any, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

#: Endpoint paths, verbatim from the vendor's ``openapi.json``.
PATH_MODELS: Final = "/v1/models"
PATH_SYSTEMONE: Final = "/v1/systemone"

#: Every model below is immutable and refuses a field the vendor did not document.
_FROZEN: Final = ConfigDict(extra="forbid", frozen=True)


def _require_json(value: Any) -> Any:
    """Reject anything the JSON encoder cannot represent (bytes, sets, objects)."""
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"value is not JSON-serializable: {exc}") from exc
    return value


#: The vendor's ``string | object | array``: any JSON value, and only JSON.
JsonValue = Annotated[Any, AfterValidator(_require_json)]

#: A calibrated probability — every probability the vendor returns is in ``[0, 1]``.
Probability = Annotated[float, Field(ge=0.0, le=1.0)]


# ---------------------------------------------------------------------------
# Questions (request side)
# ---------------------------------------------------------------------------


class NoulQuestion(BaseModel):
    """A yes/no question; the answer is the probability that the answer is *true*."""

    model_config = _FROZEN

    type: Literal["noul"] = "noul"
    instructions: JsonValue
    criteria: dict[str, JsonValue] | None = None


class ChoiceQuestion(BaseModel):
    """A single-choice question: ``criteria`` names each choice and when it applies."""

    model_config = _FROZEN

    type: Literal["choice"] = "choice"
    criteria: dict[str, JsonValue] = Field(min_length=1)
    instructions: JsonValue | None = None


class ScoreQuestion(BaseModel):
    """An ordered-scale question: a criterion's *position* is its score."""

    model_config = _FROZEN

    type: Literal["score"] = "score"
    criteria: list[JsonValue] = Field(min_length=1)
    instructions: JsonValue | None = None


#: One question, discriminated by its ``type`` field exactly as the API does.
Question = Annotated[NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")]


# ---------------------------------------------------------------------------
# Answers (response side)
# ---------------------------------------------------------------------------


class NoulAnswer(BaseModel):
    """``noul``: the probability that the yes/no question is true."""

    model_config = _FROZEN

    type: Literal["noul"] = "noul"
    noul: Probability


class ChoiceAnswer(BaseModel):
    """``choice``: the selected name plus the distribution it was selected from."""

    model_config = _FROZEN

    type: Literal["choice"] = "choice"
    choice: str
    confidence: Probability
    probabilities: dict[str, Probability] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_choice(self) -> ChoiceAnswer:
        if self.choice not in self.probabilities:
            raise ValueError(
                f"selected choice {self.choice!r} is absent from its own probabilities"
            )
        return self


class ScoreAnswer(BaseModel):
    """``score``: the position on the ordered scale, with its legend restated."""

    model_config = _FROZEN

    type: Literal["score"] = "score"
    score: float = Field(ge=0.0)
    confidence: Probability
    legend: dict[str, str] = Field(min_length=1)
    probabilities: dict[str, Probability] = Field(min_length=1)


#: One answer, discriminated by its ``type`` field exactly as the API does.
Answer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]


# ---------------------------------------------------------------------------
# Envelopes
# ---------------------------------------------------------------------------


class SystemOneRequest(BaseModel):
    """``POST /v1/systemone`` — the request envelope; all three fields are required."""

    model_config = _FROZEN

    model: str = Field(min_length=1)
    state: JsonValue
    questions: dict[str, Question] = Field(min_length=1)


class Usage(BaseModel):
    """Token accounting. Output tokens are free; input tokens are what we spend."""

    model_config = _FROZEN

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class SystemOneResponse(BaseModel):
    """``POST /v1/systemone`` — the response envelope."""

    model_config = _FROZEN

    model: str = Field(min_length=1)
    answers: dict[str, Answer] = Field(min_length=1)
    usage: Usage

    def answer_for(self, name: str) -> Answer | None:
        """The answer to question ``name``, or ``None`` when the model skipped it."""
        return self.answers.get(name)


class ModelInfo(BaseModel):
    """One entry of ``GET /v1/models``."""

    model_config = _FROZEN

    name: str = Field(min_length=1)
    description: str
    release_date: str


class ModelsResponse(BaseModel):
    """``GET /v1/models`` — the only way to learn a model name that actually exists."""

    model_config = _FROZEN

    models: list[ModelInfo]


# ---------------------------------------------------------------------------
# The advisory sidecar record
# ---------------------------------------------------------------------------


class JudgeStatus(StrEnum):
    """What happened to one judge attempt. Never a claim status."""

    ASSESSED = "assessed"
    SKIPPED = "skipped"
    FAILED = "failed"


class AgreementChoice(StrEnum):
    """The three choice names of the second-opinion question."""

    AGREE = "agree"
    AGREE_BUT_LOW_CONFIDENCE = "agree_but_low_confidence"
    DISAGREE = "disagree"


class AttentionLevel(StrEnum):
    """The ordered scale of the attention question; position is the score."""

    CAN_WAIT = "can wait"
    THIS_WEEK = "needs attention this week"
    TODAY = "needs attention today"


class AdvisorySummary(BaseModel):
    """The derived second opinion — the only part of an assessment meant to be read.

    These are *advisory* numbers. Nothing here is a status, a severity, an
    evidence pointer, a corrective action or a routing decision, and nothing here
    may be merged into a graded result record.
    """

    model_config = _FROZEN

    grounded_probability: Probability | None = None
    agreement: AgreementChoice | None = None
    agreement_confidence: Probability | None = None
    attention_score: float | None = None
    attention_level: AttentionLevel | None = None


class JudgeAssessment(BaseModel):
    """One judge attempt, keyed by ``(claim_id, rule_id)`` — a sidecar, never a result.

    ``questions`` and ``answers`` are kept raw as well as derived, so a human can
    re-read exactly what was asked and exactly what came back without trusting
    :class:`AdvisorySummary`. ``status`` is this layer's own vocabulary
    (``assessed | skipped | failed``) and shares no value domain with the graded
    record's ``status``.
    """

    model_config = _FROZEN

    claim_id: str
    rule_id: str
    status: JudgeStatus
    reason: str
    provider: str
    model: str | None = None
    questions: dict[str, Question] = Field(default_factory=dict)
    answers: dict[str, Answer] = Field(default_factory=dict)
    advisory: AdvisorySummary = Field(default_factory=AdvisorySummary)
    usage: Usage | None = None
    latency_ms: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        """The ``(claim_id, rule_id)`` pair this assessment belongs to."""
        return (self.claim_id, self.rule_id)

    @property
    def assessed(self) -> bool:
        """True only when the model actually answered."""
        return self.status is JudgeStatus.ASSESSED

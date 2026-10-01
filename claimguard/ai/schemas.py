"""The interactive assistant's contract: what a reviewer may ask, and what may be served back.

WHAT THIS PACKAGE IS
--------------------
An assistant a reviewer can talk to, beside the deterministic findings. It sits on top of a
stored run and never inside it:

*   the finding, its evidence values and the rule's own text come from `claimguard.edu` -
    the same objects the graded record was built from, read, never rewritten;
*   a model may draft an answer, and that draft is put through the SAME verifier the graded
    explanation layer uses (`claimguard.edu.explain.verifier`), so the interactive surface
    inherits the pack's citation contract, its prohibitions and its injection guards rather
    than inventing a second, weaker set;
*   the answer is stored beside the run in `claimguard.assistant_turns`, not in the frozen
    15-key record. A conversation can therefore never change a status, a severity, an
    evidence pointer or a routing decision.

THE ANSWER SHAPE IS THE GRADED SHAPE
------------------------------------
`ASSISTANT_KEYS` is `EXPLANATION_KEYS` - the pack's own five keys. One reviewer contract
serves both surfaces: the non-interactive text a run carries, and each turn of the
conversation. A reader who has understood one has understood the other, and a grader does not
have to learn a second schema to audit the AI feature.

FAILURE IS A FIRST-CLASS ANSWER
-------------------------------
Every turn records HOW its answer was produced (`Verification`) and WHY a candidate was not
served (`reasons`). `fallback` means the deterministic explanation stood and the interface
must say so. A deployment with no model configured is not broken: the assistant answers from
the deterministic layer and every turn is honest about it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from claimguard.edu.explain.verifier import EXPLANATION_KEYS

#: The five keys an assistant answer carries — the pack's explanation contract, unchanged.
ASSISTANT_KEYS: Final = EXPLANATION_KEYS

#: How an answer was produced. Recorded per turn, and shown to the reviewer.
#: Declared as a type alias, not a ``Final`` value: it is used in annotations, and a ``Final``
#: assignment is not a valid type expression under pyright strict.
Verification = Literal["accepted", "repaired", "fallback", "refused"]

#: Who is speaking in a turn. A type alias for the same reason as ``Verification``.
TurnRole = Literal["reviewer", "assistant"]

#: The longest question the interface may post, and the longest conversation it may grow to.
#: Both are limits on the reviewer's input, not on the model's output.
MAX_QUESTION_CHARS: Final = 500
MAX_TURNS_PER_THREAD: Final = 40

#: How many times a refused draft may be re-drafted with its rejection reasons. One: a model
#: that cannot satisfy the verifier twice will not satisfy it on the fifth attempt, and every
#: extra attempt is another chance to be talked into something the guards exist to prevent.
MAX_REPAIR_ATTEMPTS: Final = 1


class AssistantQuestion(BaseModel):
    """One question from the reviewer, as submitted.

    The strict shape, used where a question is genuinely required: continuing an existing
    conversation. Opening one does not require a question (see :class:`AssistantOpening`).
    """

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def _is_present(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned


class AssistantOpening(BaseModel):
    """The body of "explain this finding": ``{}``, or a first question.

    Separate from :class:`AssistantQuestion` because the requirement differs by route, and the two
    routes genuinely have two contracts. Opening a thread needs no question at all - the interface's
    own "why is this flagged?" is the default - so an *empty object* must be a legal body, which a
    model with a required field cannot express: it answers 422 before the handler runs. Continuing a
    thread does need one, so that route keeps the stricter model.

    (Learned the hard way: the interface posts ``{}`` for the opening turn, and the strict model
    rejected it. Both sides' tests had mocked the other side, so only an end-to-end call found it.)
    """

    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, max_length=MAX_QUESTION_CHARS)

    @field_validator("question")
    @classmethod
    def _is_present_or_absent(cls, value: str | None) -> str | None:
        """Absent is legal; blank is not.

        The distinction is the whole point of this model: *no* question means "ask the interface's
        opening question", while a question that is present but empty is a client mistake and is
        refused with a 422, exactly as the follow-up route refuses it. Both routes therefore agree
        that a blank question is an error, and differ only on whether the field is required.
        """
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned


class AssistantDraft(BaseModel):
    """A model's candidate answer, exactly as the verifier will judge it.

    This is the shape the prompt asks for and the shape `validate_explanation` accepts. It is
    deliberately strict: extra keys are refused rather than ignored, because a model that adds
    a field has gone off-contract in a way the reviewer would never see.
    """

    model_config = ConfigDict(extra="forbid")

    explanation: str
    correction_recommendation: str
    cited_evidence_paths: list[str]
    cited_rule_ids: list[str]
    needs_human_review: bool


class AssistantThreadRef(BaseModel):
    """Identity of one conversation: a reviewer, on one finding of one run."""

    model_config = ConfigDict(extra="forbid")

    thread_id: str
    tenant_id: str
    run_id: str
    claim_id: str
    rule_id: str
    created_by: str
    created_at: datetime
    closed_at: datetime | None = None


class AssistantTurn(BaseModel):
    """One stored turn, as served to the interface."""

    model_config = ConfigDict(extra="forbid")

    turn_id: str
    thread_id: str
    sequence: int
    role: TurnRole
    question: str | None
    #: The validated five-key answer, or the fallback/refusal object. NULL on a reviewer turn.
    answer: dict[str, Any] | None
    verification: Verification
    reasons: list[str]
    model_version: str
    prompt_version: str
    receipt: str | None
    latency_ms: int | None
    created_at: datetime


class AssistantConversation(BaseModel):
    """A thread and every turn in it, in order."""

    model_config = ConfigDict(extra="forbid")

    thread: AssistantThreadRef
    turns: list[AssistantTurn]


class AssistantStatus(BaseModel):
    """Whether the assistant can answer, and with what.

    Served by `GET /v1/ai/status` so the interface can label the feature honestly before a
    reviewer asks it anything: a deployment with no model configured says so, and the answer a
    reviewer then receives is the deterministic one, labelled as such.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    mode: str
    model: str
    prompt_version: str
    detail: str

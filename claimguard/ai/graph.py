"""The assistant's reasoning core: one question, one finding, one verified answer.

WHAT IT IS
----------
A LangGraph state machine that answers a reviewer's question about ONE stored
finding. It reads; it never writes. The finding, the claim envelope, the rule's
catalogue entry and the claim's policy values are handed in by the caller (the
API layer, which read them from the database) and are never mutated — the
conversation is stored beside the run in `claimguard.assistant_turns`, and the
frozen 15-key result record is not touched by anything in this module.

    START ──▶ guard_scope ──▶ gather ──▶ draft ──▶ verify ──▶ finalize ──▶ END
                   │                      │         │  ▲
                   │                      │         │  └─── repair   (at most MAX_REPAIR_ATTEMPTS)
                   │                      ▼         ▼
                   │                  fallback ──▶ finalize
                   └──▶ finalize      (out of scope ─▶ refused, no model asked)

*   `guard_scope` is DETERMINISTIC and first. It refuses a question that asks the
    assistant to decide a claim, to give clinical advice, to speak about another
    claim, or to take instructions that arrive inside the question. This line
    needs no model, so it cannot be talked out of anything, and it holds even if
    every model call below it fails.
*   `gather` is DETERMINISTIC. It collects the finding's own fields, re-resolves
    every evidence pointer against the ORIGINAL envelope, takes the rule's text
    and the policy values that rule reads (`claimguard.ai.tools`), plus the exact
    answer contract the verifier will enforce.
*   `draft` is the ONLY model call.
*   `verify` puts the draft through the SAME verifier the graded explanation
    layer uses: citations must resolve in the original claim, no adjudication or
    clinical assertion, no rule-echoing, and the finding's human-review boundary
    copied exactly. `repaired` means it passed on the one bounded retry that was
    given the verifier's reasons.
*   `fallback` serves the deterministic explanation (`claimguard.edu.explain.fallback`)
    whenever the model is off, missing, unreachable, malformed, or still refused.
*   `finalize` hashes the served answer and records the latency.

WHY THE VERIFIER IS NOT NEGOTIABLE
----------------------------------
An answer a model wrote is never served unchecked, not even when the model is
confident, and not even when the reviewer asked for it. `needs_human_review` is
copied from the finding, never re-derived: no conversation can lift a human
review, and none can change a status, a severity or an evidence pointer.

FAILURE IS AN ANSWER
--------------------
Nothing a model does raises out of `answer_question`. Absent library, absent key,
timeout, malformed JSON, refused draft — each becomes an `AssistantOutcome` whose
`verification` is `fallback` and whose `reasons` say what happened, so the
reviewer always receives the deterministic explanation and always sees that it
is the deterministic one. When LangGraph itself is not installed the same nodes
run in the same order in plain Python with the model treated as off, which is why
this module can be imported — and the `/v1/ai/status` route answered — on an
install without the `agent` extra.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol, TypedDict, cast

from claimguard.ai.config import MODE_OPENAI_COMPATIBLE, AssistantSettings
from claimguard.ai.errors import AssistantDraftError, AssistantInputError
from claimguard.ai.prompts import (
    OPENING_QUESTION,
    PROMPT_VERSION,
    draft_user_prompt,
    repair_user_prompt,
    system_prompt,
)
from claimguard.ai.schemas import (
    ASSISTANT_KEYS,
    MAX_QUESTION_CHARS,
    MAX_REPAIR_ATTEMPTS,
    AssistantStatus,
    Verification,
)
from claimguard.ai.tools import (
    answer_contract,
    claim_service_codes,
    envelope_values,
    finding_context,
    policy_context,
    rule_context,
)
from claimguard.edu.explain.fallback import (
    FallbackError,
    build_explanation,
    mark_deterministic,
    mark_model,
)
from claimguard.edu.explain.provider import default_transport
from claimguard.edu.explain.verifier import (
    ExplanationRejectionError,
    instruction_like,
    validate_explanation,
)

# ---------------------------------------------------------------------------
# The outcome
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AssistantOutcome:
    """One served turn: the answer, how it was produced, and why not otherwise.

    Frozen, and `answer` is the exact object that was verified — a caller cannot
    edit the text a reviewer was shown, and the receipt below describes exactly
    what is in it.
    """

    #: The five `ASSISTANT_KEYS`, or the deterministic explanation object.
    answer: dict[str, Any]
    #: `accepted` (a model drafted it and the verifier passed it),
    #: `repaired` (it passed on the one bounded retry), `fallback` (no model text
    #: was served) or `refused` (the question was out of scope).
    verification: Verification
    #: Why a candidate was not served. Empty when `accepted`.
    reasons: tuple[str, ...]
    #: e.g. `groq:qwen/qwen3.8-27b`, or `none` when no model ran.
    model_version: str
    #: The prompt version recorded on the turn.
    prompt_version: str
    #: SHA-256 (hex) over the served answer's canonical JSON, or `None` on a refusal.
    receipt: str | None
    #: Wall-clock milliseconds spent in this module.
    latency_ms: int


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


class _StateInputs(TypedDict):
    """What :func:`answer_question` always puts in the state before the graph starts.

    These keys are *required*: a node may read any of them without checking, which
    is what makes each node's body readable as a straight line.
    """

    finding: Mapping[str, Any]
    envelope: Mapping[str, Any]
    rule: Mapping[str, Any]
    policy: Mapping[str, Any]
    question: str
    history: tuple[Mapping[str, Any], ...]
    settings: AssistantSettings
    started: float
    reasons: tuple[str, ...]
    attempts: int
    model_version: str


class AssistantState(_StateInputs, total=False):
    """The graph's state: the required inputs, then whatever each node adds.

    The node-written keys are optional so a node returns a *partial* update — the
    shape LangGraph merges — and so a reader can see the whole data flow of one
    turn in one place.
    """

    # guard_scope
    verification: Verification
    # gather
    context: dict[str, Any]
    # draft
    candidate: dict[str, Any] | None
    base_prompt: str
    # verify
    rejection: tuple[str, ...]
    answer: dict[str, Any]
    # finalize
    outcome: AssistantOutcome


# ---------------------------------------------------------------------------
# Scope: the deterministic first line of defence
# ---------------------------------------------------------------------------


#: Questions that ask the assistant to make or recommend an adjudication. The
#: verdict words are narrowed deliberately: `authorization` is part of R008's
#: subject matter and must stay askable, while `approve`/`deny`/`payment` are
#: outcomes this layer never touches.
_DECISION_WORDS: Final = re.compile(
    r"\b(?:approv\w*|deni\w*|deny|reject\w*|pay|paid|payments?|payouts?|reimburs\w*"
    r"|adjudicat\w*|finali[sz]\w*|decid\w*|decision|settle\w*|sign[ -]?off)\b"
    # Pricing and billing DECISIONS, as opposed to the claim's own amounts, which stay
    # askable: "is the net amount correct?" is a question about this finding.
    r"|\bhow much (?:should|shall|can|could|will|would|do|does|did)\s+"
    r"(?:we|i|the clinic|the hospital)\b"
    r"|\bwhat (?:should|shall|can|do|does|did)\s+(?:we|i)\s+"
    r"(?:bill|charge|pay|invoice|reimburse)\b"
    r"|\b(?:negotiat\w*|write[ -]?off|fee schedule)\b",
    re.IGNORECASE,
)

#: Questions that ask for clinical advice or a clinical judgement.
_CLINICAL_WORDS: Final = re.compile(
    r"\bmedically necessary\b"
    r"|\bclinically (?:indicated|necessary|appropriate|justified)\b"
    r"|\bthe patient (?:needs|requires)\b"
    r"|\bdiagnosis (?:confirms|indicates|proves)\b"
    r"|\b(?:medical|clinical|treatment|diagnostic) advice\b"
    r"|\b(?:diagnose|prognosis)\b"
    r"|\bis (?:this|the) (?:treatment|therapy|diagnosis|medication)\b"
    r"|\bwhat should the patient\b"
    r"|\bdoes the patient (?:need|require)\b"
    # Any question whose SUBJECT is the patient's own state rather than the record:
    # "is this patient diabetic?", "should the patient take ...", "what is the patient's
    # condition?". Written as verb + article + "patient" so that `patient_id` - a field
    # name, with no word boundary between "patient" and "_" - stays askable.
    r"|\b(?:is|are|was|were|does|do|did|can|could|should|will|would|has|have|had)\s+"
    r"(?:the|this|our|that)\s+patient\b"
    r"|\b(?:what|which)\s+(?:condition|illness|disease|disorder)\b"
    r"|\bpatient(?:'s)?\s+(?:condition|health|prognosis|medication|symptoms?)\b",
    re.IGNORECASE,
)

#: Questions that try to change the assistant's rules, role or output shape.
#: :func:`claimguard.edu.explain.verifier.instruction_like` covers the direct
#: "ignore previous instructions" family (including base64-obfuscated text); this
#: adds the second-person and role-play phrasings it does not.
_INJECTION_WORDS: Final = re.compile(
    r"\bignore\b[^.!?]{0,40}\binstructions?\b"
    r"|\bdisregard\b[^.!?]{0,40}\b(?:instructions?|rules?|prompt)\b"
    r"|\b(?:new|updated)\b[^.!?]{0,20}\binstructions?\b"
    r"|\bsystem prompt\b|\breveal\b[^.!?]{0,30}\bprompt\b"
    r"|\byou are (?:now|no longer)\b|\bact as\b|\bpretend\b|\broleplay\b"
    r"|\bdeveloper mode\b|\bjailbreak\b|\bprompt injection\b"
    r"|\b(?:override|bypass)\b[^.!?]{0,30}\b(?:rules?|guards?|verifier|instructions?)\b",
    re.IGNORECASE,
)

#: Obvious requests about something other than this claim. Deliberately a short
#: list rather than a topic classifier: anything subtler is caught when the
#: verifier refuses an answer that is not about this finding's evidence.
_OFF_TOPIC_WORDS: Final = re.compile(
    r"\b(?:write|draft) (?:me )?(?:an? )?(?:email|poem|essay|story|code|script|letter)\b"
    r"|\bweather\b|\bjoke\b|\btranslate\b|\bcapital of\b|\bstock price\b|\brecipe\b"
    r"|\bwho (?:is|was) the (?:president|ceo|prime minister)\b"
    # Topics a reviewer has no reason to raise at a claim record. Each one also closes a shape
    # that the short-question path could otherwise reach once its guidance words are in play.
    r"|\b(?:football|basketball|sports?|match|olympics?|movie|film|song|music|celebrity)\b"
    r"|\b(?:news|headlines|election|politics|president|prime minister|government)\b"
    r"|\b(?:crypto|bitcoin|stock market|shares?|invest(?:ment|ing)?|lottery)\b"
    r"|\b(?:tall|high) is the (?:eiffel|burj|statue)\b|\bwhat time is it\b"
    # A known probe for "does this thing have a topic at all", and the one shape the
    # short-question path above can otherwise reach through the word "meaning".
    r"|\bmeaning of life\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Grounding: a question must be ABOUT this finding
#
# A blocklist cannot do this job, and pretending otherwise shipped a real leak: with
# only the patterns above, "Who won the 2022 World Cup?", "Write me a Python script to
# scrape LinkedIn." and "Is this patient diabetic?" were all ANSWERED, because each one
# happens to avoid every listed phrase and the verifier only checks the SHAPE of the
# answer (its five keys and its citations), not whether the answer is about the claim.
#
# So scope is decided POSITIVELY instead: a question is in scope when it shares at least
# one word with the vocabulary of the finding in front of the reviewer - the rule's own
# text, the fields its evidence points at, the claim's identifiers and structure, the
# policy, and anything already said in this conversation. A question that shares nothing
# with any of that is not about this claim, whatever it is about.
#
# The two-word categories below exist because some words are true of ANY claim sentence
# and therefore prove nothing on their own. Without that list "is this patient diabetic?"
# would pass on the word "patient" alone.
# ---------------------------------------------------------------------------

#: Words that appear in almost any sentence about a claim record. They are removed from the
#: anchor vocabulary because sharing one of them says nothing about the subject of a question.
_GENERIC_WORDS: Final[frozenset[str]] = frozenset(
    {
        "about",
        "after",
        "again",
        "against",
        "amount",
        "amounts",
        "another",
        "because",
        "before",
        "being",
        "between",
        "check",
        "checks",
        "claim",
        "claims",
        "could",
        "data",
        "date",
        "dates",
        "does",
        "doing",
        "done",
        "each",
        "else",
        "even",
        "every",
        "field",
        "fields",
        "find",
        "found",
        "from",
        "given",
        "have",
        "having",
        "here",
        "into",
        "just",
        "line",
        "lines",
        "made",
        "make",
        "many",
        "more",
        "most",
        "much",
        "must",
        "need",
        "needs",
        "other",
        "over",
        "patient",
        "please",
        "record",
        "records",
        "result",
        "results",
        "rule",
        "rules",
        "same",
        "severity",
        "should",
        "show",
        "shows",
        "some",
        "status",
        "still",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "thing",
        "things",
        "this",
        "those",
        "under",
        "value",
        "values",
        "very",
        "want",
        "well",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "will",
        "with",
        "within",
        "without",
        "would",
        "your",
        "policy",
        "member",
        "provider",
        "payer",
        "finding",
        "findings",
        "evidence",
        "code",
        "codes",
    }
)

#: A short question that talks ABOUT THE RECORD or asks for guidance on it, rather than about
#: the world: "why is this flagged?", "what should I check first?", "which evidence should I look
#: at?". Such a question carries no case NOUN, so it cannot anchor; but its subject is plainly
#: the finding on screen, so it is in scope. Together with the interrogative shape and the length
#: cap below, this is what separates "and what do I check first?" from "who won the World Cup?".
_GUIDANCE_WORDS: Final = re.compile(
    # about the record's own condition
    r"\b(?:flag\w*|fail\w*|wrong|incorrect|mismatch\w*|missing|issue\w*|problem\w*|error\w*|"
    r"discrepan\w*|unclear|confus\w*|mean\w*|matter\w*|reason\w*|cause\w*|because|happen\w*|"
    # what to do about it
    r"fix|correct\w*|resolve|recheck|recommend\w*|suggest\w*|guidance|guide|advice|advise|next|"
    r"first|priority|start)\b"
    # asking for the material itself
    r"|\b(?:check|verify|confirm|review|inspect|examine|look|see|show|read|tell|explain|help|"
    r"expect\w*|require\w*|meaning|imply|implies|"
    r"evidence|detail\w*|citation\w*|cite\w*|support\w*|provide\w*|request|ask|send|obtain|"
    r"need|give)\b",
    re.IGNORECASE,
)

#: The shape of something a reviewer types AT A FINDING: an interrogative, optionally after a
#: conversational opener ("and what do I check first?"). The shape matters as much as the words -
#: it is what keeps an imperative request ("write me an email", "summarise the news") out even
#: when it is short.
_QUESTION_SHAPE: Final = re.compile(
    r"^(?:(?:and|so|ok|okay|then|also|but)\s+)?"
    r"(?:why|how|what|which|where|when|who|can|could|should|is|are|does|do|did|will)\b",
    re.IGNORECASE,
)

#: How long a record-relative question may be before it must carry an anchor word. Long
#: questions have room to say what they are about; short ones are follow-ups by nature.
_CONTINUATION_MAX_WORDS: Final = 7

#: Shortest token kept from the anchor vocabulary. Three-letter words are too common to
#: mean anything ("end", "sum", "day"), which is the whole reason for the floor.
_MIN_ANCHOR_CHARS: Final = 4

#: Field names are split on underscores as well as punctuation: a reviewer says "which line is
#: affected", not "affected_line_ids", and a tokenizer that keeps the underscore can never match
#: the two (which is exactly how a legitimate question was refused the first time).
_PUNCTUATION: Final = re.compile(r"[^a-z0-9]+")


def _words(text: object) -> set[str]:
    """The comparable words of ``text``: lowercase alphanumeric tokens, punctuation dropped."""
    if not isinstance(text, str):
        return set()
    return {token for token in _PUNCTUATION.split(text.casefold()) if token}


def _answer_text(answer: object) -> str:
    """Every string inside a stored turn's answer, flattened for vocabulary purposes."""
    if isinstance(answer, str):
        return answer
    if isinstance(answer, Mapping):
        stored = cast("Mapping[str, Any]", answer)
        return " ".join(_answer_text(value) for value in stored.values())
    if isinstance(answer, (list, tuple)):
        stored_list = cast("Sequence[Any]", answer)
        return " ".join(_answer_text(value) for value in stored_list)
    return ""


def anchor_words(
    finding: Mapping[str, Any],
    *,
    rule: Mapping[str, Any] | None = None,
    envelope: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    history: Sequence[Mapping[str, Any]] = (),
) -> frozenset[str]:
    """The vocabulary in which a question about THIS finding can reasonably be asked.

    Built from what the reviewer is looking at, never from a topic list: the rule's identity and
    text, the fields its evidence cites, the shape and identifiers of the claim itself, the
    policy, and the conversation so far (a follow-up legitimately reuses the words the previous
    answer introduced).
    """
    words: set[str] = set()

    def add(value: object) -> None:
        words.update(_words(value))

    # The finding: its identity, its verdict words, the NAMES of its own fields (a reviewer
    # asks "which line is affected?" - `affected_line_ids` is where that word comes from) and
    # every field its evidence cites.
    for key in finding:
        add(key)
    add(finding.get("rule_id"))
    add(finding.get("claim_id"))
    add(finding.get("status"))
    add(finding.get("severity"))
    add(finding.get("explanation"))
    add(finding.get("corrective_action"))
    evidence = finding.get("evidence")
    if isinstance(evidence, Sequence):
        for entry in cast("Sequence[Any]", evidence):
            if isinstance(entry, Mapping):
                add(cast("Mapping[str, Any]", entry).get("path"))

    # The rule as the catalogue states it.
    for key in ("rule_id", "title", "logic", "corrective_action"):
        add(None if rule is None else rule.get(key))

    # The claim: its identifiers and the NAMES of its fields, which is the vocabulary a reviewer
    # naturally uses ("coverage", "service", "quantity", "authorization").
    if envelope is not None:
        for key in envelope:
            add(key)
        for key in (
            "claim_id",
            "policy_id",
            "payer_id",
            "provider_id",
            "diagnosis_code",
            "currency",
        ):
            add(envelope.get(key))
        try:
            for code in claim_service_codes(envelope):
                add(code)
        except (
            TypeError,
            ValueError,
        ):  # pragma: no cover - a malformed envelope is refused earlier
            pass

    # The policy, plus the service codes it prices.
    if policy is not None:
        add(policy.get("policy_id"))
        add(policy.get("payer_id"))
        add(policy.get("currency"))

    # What has already been said in this conversation.
    for turn in history:
        add(turn.get("question"))
        add(_answer_text(turn.get("answer")))

    return frozenset(
        word for word in words if len(word) >= _MIN_ANCHOR_CHARS and word not in _GENERIC_WORDS
    )


def in_scope(
    question: str,
    finding: Mapping[str, Any],
    *,
    rule: Mapping[str, Any] | None = None,
    envelope: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    history: Sequence[Mapping[str, Any]] = (),
) -> bool:
    """True when ``question`` is about this finding rather than about something else.

    Two ways to qualify, and no third: it shares a word with :func:`anchor_words`, or it is a
    short question whose predicate is about the record on screen ("why is this flagged?").
    """
    stripped = question.strip()
    if not stripped:
        return False
    words = _words(stripped)
    if words & anchor_words(finding, rule=rule, envelope=envelope, policy=policy, history=history):
        return True
    return bool(
        len(words) <= _CONTINUATION_MAX_WORDS
        and _QUESTION_SHAPE.match(stripped)
        and _GUIDANCE_WORDS.search(stripped)
    )


#: A claim id as the pack writes them (`PHASE1-JSON-001`), used to notice that the
#: reviewer has switched claims.
_CLAIM_ID: Final = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")
#: Any pack rule id (`R013`).
_RULE_ID: Final = re.compile(r"\bR0(?:0[1-9]|1[0-5])\b")

_REFUSAL_LEAD: Final = "I explain this stored finding; I do not decide anything."

_REFUSAL_STEP: Final = (
    "Ask about what this rule compared, the values it found, or which evidence to check "
    "next; the recorded status stays exactly as the rule engine left it."
)


def _refusal(code: str, finding: Mapping[str, Any]) -> str:
    """The reviewer-facing refusal sentence for ``code``."""
    rule_id = finding.get("rule_id")
    claim_id = finding.get("claim_id")
    where = (
        f"{rule_id} on claim {claim_id}"
        if isinstance(rule_id, str) and isinstance(claim_id, str)
        else "this finding"
    )
    body = {
        "too_long": (
            f"That question is longer than {MAX_QUESTION_CHARS} characters. Ask it in a "
            f"sentence or two and I will answer about {where}."
        ),
        "empty": f"Send a question about {where} and I will answer it.",
        "injection": (
            "I ignore instructions that arrive inside a question: my rules, my output shape "
            "and my limits are fixed and cannot be changed by the text I am asked about. "
            f"I can still explain what {where} reported."
        ),
        "decision_request": (
            "Approving, denying, paying or rejecting a claim is a reviewer's and a payer's "
            "decision, and this assistant never makes one or recommends one — not even for "
            f"this claim. I can explain why {where} was recorded and which evidence to check."
        ),
        "clinical_advice": (
            "I cannot judge a diagnosis, a treatment or whether care was necessary; that is a "
            "clinician's judgement, not a claim-explanation one. I can explain what the claim's "
            f"own data shows about {where}."
        ),
        "other_claim": (
            "That points at a different claim or rule from the finding I was opened on. I can "
            f"only explain {where}: its evidence, its rule's text and its policy values."
        ),
        "off_topic": (
            "I can only answer questions about this finding — what the rule compared, what it "
            f"observed and what evidence to check. My subject is {where}."
        ),
    }[code]
    return f"{_REFUSAL_LEAD} {body}"


def _record_value(value: Any) -> str:
    """A mapping value as a trimmed string, for pattern matching (never for output)."""
    return value.strip() if isinstance(value, str) else ""


def scope_refusal(
    question: str,
    finding: Mapping[str, Any],
    *,
    rule: Mapping[str, Any] | None = None,
    envelope: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    history: Sequence[Mapping[str, Any]] = (),
) -> str | None:
    """The refusal code for ``question``, or ``None`` when it is in scope.

    Deterministic, model-free, and total: this is the check that must hold even when nothing else
    in the graph works. The optional context (rule, envelope, policy, history) is what makes the
    GROUNDING test possible; without it only the pattern checks run, which is exactly the weaker
    behaviour that let off-topic questions through.
    """
    text = question.strip()
    if not text:
        return "empty"
    if len(text) > MAX_QUESTION_CHARS:
        return "too_long"
    if _INJECTION_WORDS.search(text) or instruction_like(text):
        return "injection"
    if _DECISION_WORDS.search(text):
        return "decision_request"
    if _CLINICAL_WORDS.search(text):
        return "clinical_advice"
    claim_id = _record_value(finding.get("claim_id"))
    if claim_id and claim_id not in text:
        # Only tokens that carry a digit are treated as another claim's id: service
        # codes are written the same way (`SVC-CONSULT`) and asking about one is a
        # question about THIS finding.
        foreign = [
            token
            for token in _CLAIM_ID.findall(text)
            if token != claim_id
            and not _RULE_ID.fullmatch(token)
            and any(character.isdigit() for character in token)
        ]
        if foreign:
            return "other_claim"
    rule_id = _record_value(finding.get("rule_id"))
    if rule_id and any(token != rule_id for token in _RULE_ID.findall(text)):
        return "other_claim"
    if _OFF_TOPIC_WORDS.search(text):
        return "off_topic"
    if not in_scope(text, finding, rule=rule, envelope=envelope, policy=policy, history=history):
        return "off_topic"
    return None


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _add_reasons(state: AssistantState, *new: str) -> tuple[str, ...]:
    """``state``'s reasons plus ``new``, de-duplicated, order preserved."""
    reasons = list(state["reasons"])
    for reason in new:
        if reason and reason not in reasons:
            reasons.append(reason)
    return tuple(reasons)


def _merge(state: AssistantState, update: Mapping[str, Any]) -> AssistantState:
    """``state`` with ``update`` applied (the merge LangGraph does for a partial node result)."""
    merged: dict[str, Any] = {**state, **update}
    return cast("AssistantState", merged)


def _refused_answer(
    finding: Mapping[str, Any], rule: Mapping[str, Any], text: str
) -> dict[str, Any]:
    """A refusal in the answer's own shape.

    A refusal carries the same five keys as any other answer — the finding's own
    citations, its rule id and its review boundary, with the refusal as the
    explanation — so a reader (and the store) never has to special-case a turn
    that has an answer but not the answer contract.
    """
    answer = build_explanation(finding, rule)
    answer["explanation"] = mark_deterministic(text)
    answer["correction_recommendation"] = mark_deterministic(_REFUSAL_STEP)
    return answer


def guard_scope(state: AssistantState) -> dict[str, Any]:
    """Node 1 — refuse an out-of-scope question before any model is involved."""
    finding = state["finding"]
    rule = state["rule"]
    code = scope_refusal(
        state.get("question", ""),
        finding,
        rule=rule,
        envelope=state.get("envelope"),
        policy=state.get("policy"),
        history=state.get("history", ()),
    )
    if code is None:
        return {"reasons": _add_reasons(state)}
    return {
        "answer": _refused_answer(finding, rule, _refusal(code, finding)),
        "verification": "refused",
        "reasons": _add_reasons(
            state, f"the question is out of scope ({code}); no model was asked"
        ),
    }


def gather(state: AssistantState) -> dict[str, Any]:
    """Node 2 — collect the finding, its evidence, the rule and the policy. No network."""
    finding = state["finding"]
    envelope = state["envelope"]
    rule_id = _record_value(finding.get("rule_id")) or _record_value(state["rule"].get("rule_id"))
    rule_view = rule_context(state["rule"])
    if rule_id:
        rule_view.setdefault("rule_id", rule_id)
    context: dict[str, Any] = {
        "finding": finding_context(finding),
        "rule": rule_view,
        "policy": policy_context(state["policy"], rule_id, claim_service_codes(envelope)),
        "envelope_values": envelope_values(envelope, finding),
        "answer_contract": answer_contract(finding),
    }
    return {"context": context}


def draft(state: AssistantState) -> dict[str, Any]:
    """Node 3 — the only model call: draft the five keys for this finding."""
    settings = state["settings"]
    if not settings.enabled:
        return {
            "candidate": None,
            "model_version": settings.model_version,
            "reasons": _add_reasons(
                state,
                f"no model was used for this turn: {settings.describe()}",
            ),
        }
    prompt = draft_user_prompt(
        context=state.get("context", {}),
        question=state["question"],
        history=state.get("history", ()),
    )
    update = _draft_from(state, prompt)
    update["base_prompt"] = prompt
    return update


def verify(state: AssistantState) -> dict[str, Any]:
    """Node 4 — the pack's verifier, applied to the draft exactly as it will be served."""
    candidate = state.get("candidate")
    if candidate is None:
        return {"rejection": (), "reasons": _add_reasons(state, "no draft was available to verify")}
    try:
        answer = validate_explanation(
            candidate, state["finding"], envelope=state["envelope"], rule=state["rule"]
        )
    except ExplanationRejectionError as exc:
        return {
            "candidate": None,
            "rejection": exc.reasons,
            "reasons": _add_reasons(state, *exc.reasons),
        }
    attempts = state.get("attempts", 0)
    return {
        "answer": answer,
        "candidate": None,
        "rejection": (),
        "verification": "repaired" if attempts else "accepted",
        "reasons": _add_reasons(state),
    }


def repair(state: AssistantState) -> dict[str, Any]:
    """Node 5 — the one bounded retry, told exactly what the verifier refused."""
    attempts = state.get("attempts", 0) + 1
    prompt = repair_user_prompt(
        prompt=state.get("base_prompt", ""), reasons=state.get("rejection", ())
    )
    update = _draft_from(state, prompt)
    update["attempts"] = attempts
    return update


def fallback(state: AssistantState) -> dict[str, Any]:
    """Node 6 — the deterministic explanation stands, and the turn says so."""
    reasons = _add_reasons(state, "the deterministic explanation stands; no model text was served")
    return {
        "answer": build_explanation(state["finding"], state["rule"]),
        "verification": "fallback",
        "model_version": state.get("model_version", "none"),
        "reasons": reasons,
    }


def finalize(state: AssistantState) -> dict[str, Any]:
    """Node 7 — hash the served answer, time the turn, build the outcome."""
    answer = state.get("answer")
    if answer is None:
        raise AssistantInputError("the assistant produced no answer for a usable finding")
    verification = state.get("verification", "fallback")
    outcome = AssistantOutcome(
        answer=answer,
        verification=verification,
        reasons=state.get("reasons", ()),
        model_version=state.get("model_version", "none"),
        prompt_version=PROMPT_VERSION,
        receipt=None if verification == "refused" else answer_receipt(answer),
        latency_ms=_elapsed_ms(state.get("started")),
    )
    return {"outcome": outcome}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _after_guard(state: AssistantState) -> str:
    return "finalize" if state.get("verification") == "refused" else "gather"


def _after_draft(state: AssistantState) -> str:
    return "verify" if state.get("candidate") is not None else "fallback"


def _after_verify(state: AssistantState) -> str:
    if state.get("answer") is not None:
        return "finalize"
    if state.get("attempts", 0) < MAX_REPAIR_ATTEMPTS:
        return "repair"
    return "fallback"


#: The nodes, in the order they appear in the diagram, keyed by name.
_NODE_FUNCTIONS: Final[Mapping[str, Callable[[AssistantState], dict[str, Any]]]] = {
    "guard_scope": guard_scope,
    "gather": gather,
    "draft": draft,
    "verify": verify,
    "repair": repair,
    "fallback": fallback,
    "finalize": finalize,
}

#: The unconditional edges (`START`/`END`, and the conditional branches, are added
#: by the builder). `guard_scope → gather` is NOT here: it is the conditional
#: route, and an unconditional copy of it would run the deterministic path *and*
#: the refusal path for every out-of-scope question.
_EDGES: Final[tuple[tuple[str, str], ...]] = (
    ("gather", "draft"),
    ("repair", "verify"),
    ("fallback", "finalize"),
)

#: The conditional edges: source → router → {router key: target}.
_ROUTERS: Final[Mapping[str, Callable[[AssistantState], str]]] = {
    "guard_scope": _after_guard,
    "draft": _after_draft,
    "verify": _after_verify,
}
_ROUTES: Final[Mapping[str, Mapping[str, str]]] = {
    "guard_scope": {"gather": "gather", "finalize": "finalize"},
    "draft": {"verify": "verify", "fallback": "fallback"},
    "verify": {"finalize": "finalize", "repair": "repair", "fallback": "fallback"},
}

#: The graph's wires, for readers (and tests) that do not want to compile it.
NODES: Final[tuple[str, ...]] = tuple(_NODE_FUNCTIONS)
GRAPH_EDGES: Final[tuple[tuple[str, str], ...]] = _EDGES
GRAPH_CONDITIONAL_EDGES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = tuple(
    (source, tuple(routes.values())) for source, routes in _ROUTES.items()
)


# ---------------------------------------------------------------------------
# The model seam
# ---------------------------------------------------------------------------


class Drafter(Protocol):
    """The one model operation the graph needs: text out, messages in.

    Declared as a protocol so a test can substitute a stub — and so the whole
    verify/repair/fallback path can be proven without a socket.
    """

    def __call__(self, messages: Sequence[tuple[str, str]]) -> str:
        """Return the model's reply text for ``(role, content)`` messages."""
        ...


def build_drafter(settings: AssistantSettings) -> Drafter:
    """Build the model seam: the only code in this module that can open a socket.

    Public on purpose: it is the one substitution point the whole model path hangs
    from, so a test can install a stub here and prove `accept`/`repair`/`fallback`
    without a socket, and a deployment can swap the client without touching the
    graph. It returns a :class:`Drafter`, not a client, because the graph only ever
    needs "text out for messages in".

    Two clients, because the two modes need different addressing:

    *   `groq` goes through `langchain-groq`, which speaks Groq's
        OpenAI-compatible API but appends `/openai/v1/chat/completions` to the
        origin it is handed — see :func:`groq_root`;
    *   `openai_compatible` goes through the same transport the graded explanation
        layer already ships and tests (`default_transport`), which posts to
        `{base_url}/chat/completions` — because the Groq SDK cannot address a
        generic endpoint, and a second HTTP client written for this module would
        be a second thing to get wrong.

    The model-library import is function-local: a deployment without the `agent`
    extra never loads it, and `_draft_from` turns the resulting `ImportError`
    into an ordinary fallback reason.
    """
    if settings.mode == MODE_OPENAI_COMPATIBLE:
        return _compatible_drafter(settings)
    return _groq_drafter(settings)


def _groq_drafter(settings: AssistantSettings) -> Drafter:
    """The Groq client, through LangChain, with the base URL the SDK expects."""
    from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
    from langchain_groq import ChatGroq
    from pydantic import SecretStr

    chat = ChatGroq(
        model=settings.model,
        api_key=SecretStr(settings.api_key) if settings.api_key else None,
        base_url=groq_root(settings.base_url),
        timeout=settings.timeout,
        max_tokens=settings.max_tokens,
        temperature=0.0,
        # No transport-level retry: `repair` is the one bounded retry, and it is
        # the one the reviewer's latency budget accounts for.
        max_retries=0,
    )

    def drafter(messages: Sequence[tuple[str, str]]) -> str:
        built: list[BaseMessage] = [
            SystemMessage(content=text) if role == "system" else HumanMessage(content=text)
            for role, text in messages
        ]
        return _reply_text(chat.invoke(built))

    return drafter


def _compatible_drafter(settings: AssistantSettings) -> Drafter:
    """Any OpenAI-compatible `/chat/completions` endpoint, over the project's own transport."""
    endpoint = f"{settings.base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.api_key}",
    }

    def drafter(messages: Sequence[tuple[str, str]]) -> str:
        payload: dict[str, Any] = {
            "model": settings.model,
            "messages": [
                {"role": "user" if role == "human" else role, "content": text}
                for role, text in messages
            ],
            "temperature": 0,
            "max_tokens": settings.max_tokens,
        }
        return _completion_text(default_transport(endpoint, headers, payload, settings.timeout))

    return drafter


#: What the Groq SDK appends to the origin it is given, and what this project's
#: own clients append `/chat/completions` to.
_GROQ_OPENAI_SUFFIX: Final = "/openai/v1"


def groq_root(base_url: str) -> str:
    """The API origin the Groq SDK expects.

    The settings carry the OpenAI-compatible URL every other client in this repo
    uses (`https://api.groq.com/openai/v1`); the Groq SDK appends its own
    `/openai/v1/chat/completions` to the origin it is handed. Both spellings are
    accepted, so an operator copying either URL gets a working client.
    """
    trimmed = base_url.rstrip("/")
    if trimmed.endswith(_GROQ_OPENAI_SUFFIX):
        return trimmed[: -len(_GROQ_OPENAI_SUFFIX)]
    return trimmed


def _completion_text(body: str) -> str:
    """The assistant text out of an OpenAI-compatible chat-completions body."""
    try:
        payload: Any = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AssistantDraftError(f"the endpoint's reply was not JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise AssistantDraftError("the endpoint's reply was not a JSON object")
    choices = cast("Mapping[str, Any]", payload).get("choices")
    if not isinstance(choices, list) or not choices:
        raise AssistantDraftError("the endpoint's reply carried no choices")
    message = cast("list[Any]", choices)[0]
    if not isinstance(message, Mapping):
        raise AssistantDraftError("the endpoint's first choice was not an object")
    content = cast("Mapping[str, Any]", message).get("message")
    if not isinstance(content, Mapping):
        raise AssistantDraftError("the endpoint's first choice carried no message")
    text = cast("Mapping[str, Any]", content).get("content")
    if not isinstance(text, str):
        raise AssistantDraftError("the endpoint's message carried no text")
    return text


def _reply_text(message: Any) -> str:
    """The text of a model reply, whether it is an `AIMessage` or a stub's string."""
    if isinstance(message, str):
        return message
    content: Any = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in cast("list[Any]", content):
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, Mapping):
                text = cast("Mapping[str, Any]", block).get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    raise AssistantDraftError(f"the model reply carried no text ({type(message).__name__})")


_FENCE: Final = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _parse_json_object(reply: str) -> dict[str, Any]:
    """The answer object out of a model reply, tolerating a wrapper or a fence."""
    text = reply.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    value = _loads(text)
    if not isinstance(value, dict):
        raise AssistantDraftError("the model reply was not a JSON object")
    return cast("dict[str, Any]", value)


def _loads(text: str) -> Any:
    """``json.loads``, retrying on the outermost braces when the reply has padding."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise AssistantDraftError("the model reply contained no JSON object") from None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AssistantDraftError(f"the model reply was not valid JSON: {exc}") from exc


def _mark_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Mark model-written text as such BEFORE verification, so the served answer is
    byte-for-byte the object the verifier approved.

    `[model] ` mirrors the graded layer's attribution: a reviewer reading a turn
    can tell which text a model wrote without extra tooling, and the marker is
    part of what is checked and hashed.
    """
    marked: dict[str, Any] = dict(candidate)
    for field in ("explanation", "correction_recommendation"):
        value = marked.get(field)
        if isinstance(value, str) and value.strip():
            marked[field] = mark_model(value)
    return marked


def _draft_from(state: AssistantState, prompt: str) -> dict[str, Any]:
    """Generate, parse and mark one draft; every fault becomes a reason, not a raise."""
    settings = state["settings"]
    try:
        drafter = build_drafter(settings)
        reply = drafter((("system", system_prompt()), ("human", prompt)))
        candidate = _mark_candidate(_parse_json_object(reply))
    except ImportError as exc:
        return {
            "candidate": None,
            "model_version": "none",
            "reasons": _add_reasons(
                state,
                f"no model was used for this turn: the model library is not installed ({exc})",
            ),
        }
    except (AssistantDraftError, OSError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        return {
            "candidate": None,
            "model_version": settings.model_version,
            "reasons": _add_reasons(
                state, f"the model's reply could not be used ({type(exc).__name__}: {exc})"
            ),
        }
    except Exception as exc:  # noqa: BLE001 - a model fault is an outcome, never a crash
        return {
            "candidate": None,
            "model_version": settings.model_version,
            "reasons": _add_reasons(state, f"the model call failed ({type(exc).__name__}: {exc})"),
        }
    return {"candidate": candidate, "model_version": settings.model_version}


# ---------------------------------------------------------------------------
# Receipts and timing
# ---------------------------------------------------------------------------


def answer_receipt(answer: Mapping[str, Any]) -> str:
    """SHA-256 (hex) over the served answer's canonical JSON.

    Over exactly the five keys in the contract's order, so the same answer always
    receipts the same and a turn that was edited after the fact no longer matches
    the receipt stored with it.
    """
    payload = {key: answer.get(key) for key in ASSISTANT_KEYS}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _elapsed_ms(started: float | None) -> int:
    """Milliseconds since ``started`` (0 when the clock was never read)."""
    if started is None:
        return 0
    return max(0, round((time.monotonic() - started) * 1000))


# ---------------------------------------------------------------------------
# The compiled graph, and the runner that does not need it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GraphApi:
    """The three LangGraph names the builder needs, resolved together."""

    START: Any
    END: Any
    StateGraph: Any


def _langgraph_api() -> _GraphApi | None:
    """LangGraph's builder API, or ``None`` when the optional dependency is absent.

    Resolved per call (and through :func:`_compiled_graph`'s cache) so that
    `import claimguard.ai.graph` never requires the `agent` extra.
    """
    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        return None
    return _GraphApi(START=START, END=END, StateGraph=StateGraph)


_COMPILED: Final[list[Any]] = []


def compiled_graph() -> Any | None:
    """The compiled state machine, or ``None`` when LangGraph is not installed."""
    if _COMPILED:
        return _COMPILED[0]
    api = _langgraph_api()
    if api is None:
        return None
    builder = api.StateGraph(AssistantState)
    for name, node in _NODE_FUNCTIONS.items():
        builder.add_node(name, node)
    builder.add_edge(api.START, "guard_scope")
    builder.add_edge("finalize", api.END)
    for source, target in _EDGES:
        builder.add_edge(source, target)
    for source, routes in _ROUTES.items():
        builder.add_conditional_edges(source, _ROUTERS[source], routes)
    graph = builder.compile()
    _COMPILED.append(graph)
    return graph


def reset_compiled_graph() -> None:
    """Forget the compiled graph (used by tests that simulate a missing LangGraph)."""
    _COMPILED.clear()


def _run_sequentially(state: AssistantState) -> AssistantState:
    """The same nodes in the same order, for a deployment without LangGraph.

    Only the *runtime* is missing here, not the guarantees: `guard_scope`,
    `gather`, `fallback` and `finalize` are ordinary functions. The model is
    treated as off — the `draft` node does not run — because a deployment without
    the agent extra never promised a model answer, and the reviewer is told
    exactly that in `reasons`.
    """
    state = _merge(state, guard_scope(state))
    if _after_guard(state) != "gather":
        return _merge(state, finalize(state))
    state = _merge(state, gather(state))
    if state["settings"].enabled:
        state = _merge(
            state,
            {
                "reasons": _add_reasons(
                    state,
                    "no model was used for this turn: the LangGraph runtime is not installed",
                )
            },
        )
    state = _merge(state, fallback(state))
    return _merge(state, finalize(state))


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def answer_question(
    *,
    finding: Mapping[str, Any],
    envelope: Mapping[str, Any],
    rule: Mapping[str, Any],
    policy: Mapping[str, Any],
    question: str | None,
    history: Sequence[Mapping[str, Any]],
    settings: AssistantSettings | None = None,
) -> AssistantOutcome:
    """Answer one reviewer's question about one stored finding, verified.

    Returns an :class:`AssistantOutcome` for every outcome a model can produce —
    refusal, acceptance, repair, fallback. Raises :class:`AssistantInputError`
    only when the finding is not a usable result record, because then there is no
    deterministic explanation to stand on and answering would mean inventing one.

    ``settings=None`` reads the environment (:meth:`AssistantSettings.from_env`).
    """
    active = AssistantSettings.from_env() if settings is None else settings
    _require_usable(finding, rule)
    state: AssistantState = {
        "finding": finding,
        "envelope": envelope,
        "rule": rule,
        "policy": policy,
        "question": _clean_question(question),
        "history": tuple(history),
        "settings": active,
        "started": time.monotonic(),
        "reasons": (),
        "attempts": 0,
        "model_version": "none",
    }
    graph = compiled_graph()
    if graph is None:
        final = _run_sequentially(state)
    else:
        final = cast("AssistantState", graph.invoke(state))
    outcome = final.get("outcome")
    if outcome is None:  # pragma: no cover - `finalize` always runs and always sets it
        raise AssistantInputError("the assistant's graph produced no outcome")
    return outcome


def assistant_status(settings: AssistantSettings | None = None) -> AssistantStatus:
    """Whether the assistant can use a model here, and with what — never the key."""
    active = AssistantSettings.from_env() if settings is None else settings
    runtime = "langgraph" if _langgraph_api() is not None else "sequential (langgraph is absent)"
    return AssistantStatus(
        enabled=active.enabled,
        mode=active.mode,
        model=active.model,
        prompt_version=PROMPT_VERSION,
        detail=f"{active.describe()} graph={runtime}",
    )


def _clean_question(question: str | None) -> str:
    """The reviewer's question, or the interface's opening question, whitespace-collapsed."""
    if question is None:
        return OPENING_QUESTION
    return " ".join(question.split())


def _require_usable(finding: Mapping[str, Any], rule: Mapping[str, Any]) -> None:
    """Refuse a record the deterministic path could not explain, before any work.

    Calling :func:`build_explanation` here is what makes "there is always a
    fallback answer" structural rather than hopeful: if the deterministic builder
    refuses the record, no answer exists to serve, and the caller is told so
    instead of being given invented text.
    """
    try:
        build_explanation(finding, rule)
    except FallbackError as exc:
        raise AssistantInputError(str(exc)) from exc


__all__ = [
    "GRAPH_CONDITIONAL_EDGES",
    "GRAPH_EDGES",
    "NODES",
    "AssistantOutcome",
    "AssistantState",
    "Drafter",
    "answer_question",
    "answer_receipt",
    "assistant_status",
    "build_drafter",
    "compiled_graph",
    "draft",
    "fallback",
    "finalize",
    "gather",
    "groq_root",
    "guard_scope",
    "repair",
    "reset_compiled_graph",
    "scope_refusal",
    "verify",
]

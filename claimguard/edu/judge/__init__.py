"""The advisory JEV judge: a second opinion that sits *outside* the graded contract.

TypeSafe's Jev ("System One") is a typed probabilistic model: it takes
unstructured state in and returns schema-matched decisions out — a probability, a
named choice, a position on a scale — never generated text. This subpackage uses
it as an **adjudicator**: after the deterministic engine has produced its 15-key
records, the judge is asked three bounded questions about each finding (is the
explanation grounded in the cited evidence; does a second opinion agree with the
rule's status; how much human attention does this deserve) and its answers are
written to a sidecar keyed by ``(claim_id, rule_id)``.

Layout:

*   :mod:`claimguard.edu.judge.models`    — the typed mirror of the HTTP contract
*   :mod:`claimguard.edu.judge.config`    — environment settings (no key → disabled)
*   :mod:`claimguard.edu.judge.provider`  — ``NullJudge`` (default) and ``JevJudge``
*   :mod:`claimguard.edu.judge.questions` — the three questions and the state they see
*   :mod:`claimguard.edu.judge.sidecar`   — the JSONL store, and the merge guard
*   :mod:`claimguard.edu.judge.run`       — one record in, one assessment out
*   :mod:`claimguard.cli.judge`           — ``claimguard judge probe|assess``

What this layer can never do — enforced structurally, not by convention:

*   change a status, a severity, an evidence pointer, a corrective action or any
    routing the deterministic rules produced. Judge output lives in its own
    record type, and :func:`~claimguard.edu.judge.sidecar.separate` refuses a
    result record whose key set is not exactly the frozen 15;
*   run, or dial out, without an API key: with none, the provider is
    :class:`~claimguard.edu.judge.provider.NullJudge` and every assessment is
    ``skipped``;
*   turn a fault into a failure of the run: a timeout, a 4xx/5xx, a malformed
    body or an unexpected answer type is recorded as ``failed`` and nothing else
    changes.
"""

from __future__ import annotations

from claimguard.edu.judge.config import (
    ENV_API_KEY,
    ENV_BASE_URL,
    ENV_MODEL,
    ENV_TIMEOUT,
    JudgeSettings,
)
from claimguard.edu.judge.models import (
    AdvisorySummary,
    AgreementChoice,
    Answer,
    AttentionLevel,
    ChoiceAnswer,
    ChoiceQuestion,
    JudgeAssessment,
    JudgeStatus,
    ModelInfo,
    ModelsResponse,
    NoulAnswer,
    NoulQuestion,
    Question,
    ScoreAnswer,
    ScoreQuestion,
    SystemOneRequest,
    SystemOneResponse,
    Usage,
)
from claimguard.edu.judge.provider import (
    HttpRequest,
    JevJudge,
    JudgeDisabledError,
    JudgeError,
    JudgeHTTPError,
    JudgeProvider,
    JudgeResponseError,
    JudgeTransport,
    JudgeTransportError,
    NullJudge,
    ProbeReport,
    build_provider,
    default_transport,
)
from claimguard.edu.judge.questions import (
    QUESTION_ATTENTION,
    QUESTION_GROUNDED,
    QUESTION_NAMES,
    QUESTION_STATUS_AGREEMENT,
    QuestionError,
    build_body,
    build_envelope,
    build_questions,
    build_state,
    rule_excerpt,
)
from claimguard.edu.judge.run import (
    REASON_ASSESSED,
    REASON_EVIDENCE,
    REASON_NO_CLAIM,
    REASON_NO_RULE,
    assess_record,
    assess_records,
    derive_advisory,
    load_claim_envelopes,
    load_rule_manifest,
)
from claimguard.edu.judge.sidecar import (
    SidecarError,
    append_assessments,
    assert_graded_records,
    index_assessments,
    pair_records,
    read_assessments,
    separate,
    summarize,
    write_assessments,
)

__all__ = [
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_MODEL",
    "ENV_TIMEOUT",
    "QUESTION_ATTENTION",
    "QUESTION_GROUNDED",
    "QUESTION_NAMES",
    "QUESTION_STATUS_AGREEMENT",
    "REASON_ASSESSED",
    "REASON_EVIDENCE",
    "REASON_NO_CLAIM",
    "REASON_NO_RULE",
    "AdvisorySummary",
    "AgreementChoice",
    "Answer",
    "AttentionLevel",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "HttpRequest",
    "JevJudge",
    "JudgeAssessment",
    "JudgeDisabledError",
    "JudgeError",
    "JudgeHTTPError",
    "JudgeProvider",
    "JudgeResponseError",
    "JudgeSettings",
    "JudgeStatus",
    "JudgeTransport",
    "JudgeTransportError",
    "ModelInfo",
    "ModelsResponse",
    "NoulAnswer",
    "NoulQuestion",
    "NullJudge",
    "ProbeReport",
    "Question",
    "QuestionError",
    "ScoreAnswer",
    "ScoreQuestion",
    "SidecarError",
    "SystemOneRequest",
    "SystemOneResponse",
    "Usage",
    "append_assessments",
    "assert_graded_records",
    "assess_record",
    "assess_records",
    "build_body",
    "build_envelope",
    "build_provider",
    "build_questions",
    "build_state",
    "default_transport",
    "derive_advisory",
    "index_assessments",
    "load_claim_envelopes",
    "load_rule_manifest",
    "pair_records",
    "read_assessments",
    "rule_excerpt",
    "separate",
    "summarize",
    "write_assessments",
]

"""Run the application's real seams with an offline model callback. No database writes."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast
from unittest.mock import patch

from claimguard.ai.config import AssistantSettings
from claimguard.ai.graph import answer_question
from claimguard.benchmark.corpus import fingerprint
from claimguard.benchmark.scoring import score_output
from claimguard.edu.explain.provider import (
    ModelExplanationProvider,
    ModelSettings,
    explain_finding,
    untrusted_text_for,
)

Generate = Callable[[list[dict[str, str]]], str]


def run_explanation(case: Mapping[str, Any], generate: Generate) -> dict[str, Any]:
    """Keep the exact raw draft and served answer separate, using production parsing."""
    raw: list[str] = []
    candidate: dict[str, Any] = {}
    initial = fingerprint(case)

    def transport(
        url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout: float
    ) -> str:
        reply = generate(cast(list[dict[str, str]], payload["messages"]))
        raw.append(reply)
        return json.dumps({"choices": [{"message": {"content": reply}}]})

    delegate = ModelExplanationProvider(
        ModelSettings(base_url="https://offline.invalid/v1", model="offline-benchmark"),
        transport=transport,
    )

    class Recorder:
        name = "model"
        source_kind = "model"

        def explain(
            self,
            finding: Mapping[str, Any],
            rule: Mapping[str, Any],
            *,
            untrusted_text: str | None = None,
        ) -> Mapping[str, Any]:
            parsed = delegate.explain(finding, rule, untrusted_text=untrusted_text)
            candidate.update(parsed)
            return parsed

    outcome = explain_finding(
        case["finding"],
        case["rule"],
        Recorder(),
        envelope=case["envelope"],
        untrusted_text=untrusted_text_for(case["envelope"]),
    )
    if fingerprint(case) != initial:
        raise RuntimeError("Benchmark must not mutate deterministic inputs")
    served = outcome.as_output()
    return {
        "case_id": case["case_id"],
        "raw": raw,
        "candidate": candidate or None,
        "served": served,
        "raw_score": score_output(case, candidate or None, [], raw_text=raw[0] if raw else ""),
        "served_score": score_output(case, served, []),
        "fallback_used": outcome.fallback_used,
        "declined_reason": outcome.declined_reason,
        "reasons": list(outcome.rejection_reasons),
        "status_unchanged": outcome.status == case["finding"]["status"],
    }


def run_followup(
    case: Mapping[str, Any],
    question: str,
    generate: Generate,
    *,
    history: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Exercise guard/gather/draft/verify/repair/fallback in the actual assistant graph.

    Patching is restricted to this offline experiment's public model seam. No live
    application process, tenant session, tools, credentials or database is involved.
    """
    attempts: list[dict[str, Any]] = []
    initial = fingerprint(case)

    def drafter(messages: Sequence[tuple[str, str]]) -> str:
        prompt = [
            {"role": "user" if role == "human" else role, "content": content}
            for role, content in messages
        ]
        reply = generate(prompt)
        attempts.append({"prompt_hash": fingerprint(prompt), "raw": reply})
        return reply

    settings = AssistantSettings(
        mode="openai_compatible",
        model="offline-benchmark",
        base_url="https://offline.invalid/v1",
        api_key="offline-placeholder",
    )
    with patch("claimguard.ai.graph.build_drafter", return_value=drafter):
        outcome = answer_question(
            finding=case["finding"],
            envelope=case["envelope"],
            rule=case["rule"],
            policy=case["policy"],
            question=question,
            history=history,
            settings=settings,
        )
    if fingerprint(case) != initial:
        raise RuntimeError("Assistant mutated benchmark inputs")
    review_case = dict(case)
    review_case["case_hash"] = fingerprint(
        {"case": case["case_hash"], "question": question, "history": list(history)}
    )
    return {
        "case_id": case["case_id"],
        "question": question,
        "attempts": attempts,
        "served": outcome.answer,
        "verification": outcome.verification,
        "reasons": list(outcome.reasons),
        "receipt": outcome.receipt,
        "score": score_output(review_case, outcome.answer, []),
    }

"""The interface renders untrusted claim text as TEXT, never as markup.

WHAT IS UNTRUSTED
-----------------
Claim ``notes``, attachment ``text``, rule ``explanation``/``corrective_action``,
evidence values, reviewer-typed actor/reason strings and every API error body are
data. A reviewer must be able to read them; a browser must never execute or
parse them.

HOW THIS IS TESTED WITHOUT A BROWSER
------------------------------------
``claimguard/review/ui/static/render.mjs`` takes the document as an argument, so
these tests run the SHIPPED module under Node against a sealed DOM shim
(``dom_shim.mjs``) that offers only ``createElement``, ``createTextNode``,
``append`` and ``textContent``. The shim's nodes are sealed and the module is
strict mode, so a renderer that reached for ``innerHTML`` — the plausible bug
this test exists to catch — raises instead of silently passing. A second test
proves that guard is real, so the injection test cannot quietly become vacuous.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.review_ui.conftest import DOM_SHIM, HARNESS, requires_node, run_node

pytestmark = [pytest.mark.unit, requires_node]

#: A payload that would execute if it were ever written as markup.
SCRIPT_PAYLOAD = "<script>alert('xss')</script>"
#: A payload that would fire if it were ever written as an attribute.
IMG_PAYLOAD = "<img src=x onerror=alert(1)>"

_ESCAPED_SCRIPT = "&lt;script&gt;alert('xss')&lt;/script&gt;"


def render(payload: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    """Run the shipped renderers over ``payload`` and return what they produced."""
    source = tmp_path / "payload.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    return json.loads(run_node(str(HARNESS), str(source)))


def finding(record: dict[str, Any]) -> dict[str, Any]:
    """A payload that exercises the finding renderer, the queue and a refusal."""
    return {
        "finding": {
            "record": record,
            "options": {"review": {"status": "unreviewed", "actor": None, "unresolved": True}},
        }
    }


def test_the_shim_refuses_the_unsafe_sinks_it_exists_to_block() -> None:
    """The guard the injection test rests on: new properties on a node throw."""
    code = (
        f'import {{ makeDocument }} from "{DOM_SHIM.as_uri()}";'
        'const element = makeDocument().createElement("div");'
        "const outcomes = [];"
        'for (const sink of ["innerHTML", "outerHTML", "srcdoc", "onclick"]) {'
        "  try { element[sink] = '<script>alert(1)</script>'; outcomes.push(sink + ':ALLOWED'); }"
        '  catch (error) { outcomes.push(sink + ":REFUSED"); }'
        "}"
        "process.stdout.write(outcomes.join(' '));"
    )
    output = run_node("--input-type=module", "-e", code)
    assert output == "innerHTML:REFUSED outerHTML:REFUSED srcdoc:REFUSED onclick:REFUSED"


def test_untrusted_claim_text_is_shown_as_text_and_cannot_become_markup(tmp_path: Path) -> None:
    """The injection test: a script payload in claim data stays characters."""
    record = {
        "claim_id": "CG-UI-INJECTION",
        "rule_id": "R010",
        "rule_version": "1.0.0",
        "status": "UNABLE_TO_ASSESS",
        "severity": "high",
        "affected_line_ids": ["L1"],
        "evidence": [
            # The engine reads the ORIGINAL envelope, so attachment text and the
            # claim's own notes arrive here exactly as the submitter wrote them.
            {
                "path": "/attachments",
                "value": [{"text": SCRIPT_PAYLOAD, "document_status": "draft"}],
            },
            {"path": "/notes", "value": SCRIPT_PAYLOAD},
        ],
        "rule_source": "fictional-rulebook/R010@1.0.0",
        "explanation": f"The document is only a draft. {SCRIPT_PAYLOAD}",
        "corrective_action": IMG_PAYLOAD,
        "confidence": None,
        "confidence_kind": "not_probabilistic",
        "requires_human_review": True,
        "method": "deterministic",
        "review_status": "unreviewed",
    }
    rendered = render(finding(record), tmp_path)

    assert "article" in rendered["elements"]
    assert "script" not in rendered["elements"]
    assert "<script" not in rendered["html"]
    assert "<img" not in rendered["html"]
    # It is displayed, escaped, as the characters the submitter wrote.
    assert _ESCAPED_SCRIPT in rendered["html"]
    assert SCRIPT_PAYLOAD in rendered["text"]
    assert IMG_PAYLOAD in rendered["text"]
    # The original value is shown next to its pointer, not summarised away.
    assert "/attachments" in rendered["text"]
    assert "/notes" in rendered["text"]


def test_the_api_error_body_is_shown_verbatim_and_never_as_markup(tmp_path: Path) -> None:
    """A 422 is displayed, not replaced by a friendlier client-side message."""
    rendered = render(
        {
            "error": {
                "status": 422,
                "context": "The decision on R003 was refused",
                "body": {
                    "detail": [
                        {
                            "type": "value_error",
                            "loc": ["body", "actor"],
                            "msg": f"Value error, must not be blank {SCRIPT_PAYLOAD}",
                        }
                    ]
                },
            }
        },
        tmp_path,
    )
    assert "HTTP 422" in rendered["text"]
    assert "must not be blank" in rendered["text"]
    assert "actor" in rendered["text"]
    assert "script" not in rendered["elements"]
    assert "<script" not in rendered["html"]
    assert _ESCAPED_SCRIPT in rendered["html"]


def test_a_claim_identifier_from_the_api_is_also_data(tmp_path: Path) -> None:
    """Ids and reviewer strings travel the same safe path as claim text."""
    rendered = render(
        {
            "queue": {
                "items": [
                    {
                        "run_id": "RUN-0000",
                        "claim_id": f"CG-{SCRIPT_PAYLOAD}",
                        "version": 1,
                        "run_created_at": "2026-09-23T10:00:00+00:00",
                        "record": {
                            "claim_id": f"CG-{SCRIPT_PAYLOAD}",
                            "rule_id": "R003",
                            "rule_version": "1.0.0",
                            "status": "FAIL",
                            "severity": "high",
                            "affected_line_ids": [],
                            "evidence": [{"path": "/coverage/end_date", "value": "2026-03-09"}],
                            "rule_source": "fictional-rulebook/R003@1.0.0",
                            "explanation": "Coverage ended before the service date.",
                            "corrective_action": "Correct the coverage period.",
                            "confidence": None,
                            "confidence_kind": "not_probabilistic",
                            "requires_human_review": True,
                            "method": "deterministic",
                            "review_status": "unreviewed",
                        },
                        "review": {"status": "unreviewed", "unresolved": True, "decision_count": 0},
                        "needs_attention": True,
                    }
                ],
                "claims": [
                    {
                        "claim_id": f"CG-{SCRIPT_PAYLOAD}",
                        "run_id": "RUN-0000",
                        "version": 1,
                        "findings": 15,
                        "unresolved": 15,
                        "latest_decision_at": None,
                    }
                ],
            }
        },
        tmp_path,
    )
    assert "script" not in rendered["elements"]
    assert "<script" not in rendered["html"]
    assert _ESCAPED_SCRIPT in rendered["html"]
    # The unresolved count the pack requires is stated, not implied.
    assert "15" in rendered["text"]

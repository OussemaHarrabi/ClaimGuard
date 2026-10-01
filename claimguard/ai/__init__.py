"""The interactive assistant: a reviewer can ask about one finding, and never change it.

WHAT LIVES HERE
---------------
*   :mod:`claimguard.ai.schemas` — the contract: the five answer keys (the pack's
    own `EXPLANATION_KEYS`), the question and turn shapes, the limits, and the
    four ways an answer can be produced.
*   :mod:`claimguard.ai.config` — whether a model may run at all, read once from
    the environment, failing closed to `mode='off'`.
*   :mod:`claimguard.ai.prompts` — the pinned instruction, versioned, and the two
    messages the graph sends (the draft request and the one bounded repair).
*   :mod:`claimguard.ai.tools` — read-only, pure, total views of a stored run:
    the finding, its evidence pointers re-resolved against the ORIGINAL claim,
    the rule's own text, the policy values that rule reads.
*   :mod:`claimguard.ai.graph` — the LangGraph state machine that turns a question
    into a verified answer, and the deterministic first line (`guard_scope`) and
    last resort (`fallback`) around the single model call.

THE BOUNDARY, IN ONE SENTENCE
------------------------------
The assistant READS a stored run and writes only its own conversation
(`claimguard.assistant_turns`); it never writes the frozen 15-key result record,
and no answer it serves can change a status, a severity, an evidence pointer or a
routing decision.

This package's `__init__` deliberately imports nothing. The API and the review
store import `claimguard.ai.schemas` on installations that do not have the
optional `agent` extra, and pulling in LangGraph (or a model client) from here
would make importing the contract require the model runtime. Import the module
you need.
"""

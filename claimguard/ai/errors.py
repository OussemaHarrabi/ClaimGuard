"""What the assistant's reasoning core may raise — and, deliberately, what it may not.

The split here is the whole point of the module. There are exactly two ways the
assistant can fail loudly:

*   :class:`AssistantInputError` — the caller handed us something that is not a
    usable 15-key result record, so there is no finding to explain and no
    deterministic text to fall back on. The caller is wrong (the API layer
    validated the record before calling, and a broken record is their bug);
    answering anyway would mean inventing a claim, which is exactly the failure
    mode this whole feature exists to avoid.

*   :class:`AssistantDraftError` — a model replied with something that is not a
    JSON object. This one never escapes: :mod:`claimguard.ai.graph` turns it into
    a recorded reason and serves the deterministic answer.

Everything else — the model library missing, the endpoint unreachable, a
timeout, a rate limit, output the verifier refuses — is an **outcome**, not an
exception. `answer_question` returns a full `AssistantOutcome` whose
`verification` says `fallback`, because a deployment with no working model is
not a broken deployment: it is one where the deterministic explanation stands and
every turn says so.
"""

from __future__ import annotations


class AssistantError(Exception):
    """Base class for the failures the assistant's reasoning core can raise."""


class AssistantInputError(AssistantError, ValueError):
    """The finding is not a usable result record, so nothing can be explained.

    Raised before any model call and before any answer is built: the fallback
    path needs the record's own ``rule_id``, ``claim_id``, ``status``,
    ``severity``, ``explanation`` and evidence list, and a record missing them is
    not something the assistant may paper over with invented text.
    """


class AssistantDraftError(AssistantError):
    """A model's reply was not a JSON object of the five answer keys.

    Internal to the drafting path: the graph records it as a reason and falls
    back. It is raised (rather than returned) so the malformed-reply branch and
    the transport-failure branch cannot be confused by a caller.
    """

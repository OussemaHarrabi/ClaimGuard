"""Model configuration for the interactive assistant — read once, from the environment.

WHY A SETTINGS OBJECT AND NOT A GLOBAL
-------------------------------------
The deterministic assistant is always available; the model is an optional
*extra*. Which one answers is therefore a property of the deployment, not of the
code path, and it is decided in exactly one place: this module. The graph reads
`AssistantSettings` and never looks at the environment itself, so a test can
hand it a settings object with no key and prove — by monkeypatching `socket` —
that nothing opens a connection.

FAIL-CLOSED DEFAULTS
--------------------
Absence is never an error. An unset, unrecognised, half-configured or
unparseable configuration degrades to `mode='off'`: the assistant still answers,
from the deterministic layer, and every turn is labelled `fallback`. A model is
only ever used when the operator has explicitly named a mode AND supplied a key
AND a base URL resolves — the three things that together mean "a model is
actually reachable". `describe()` reports which of them is missing, and never
returns the key itself.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Literal

#: The model is not used at all: every answer comes from the deterministic path.
MODE_OFF: Final = "off"
#: Groq's OpenAI-compatible endpoint, spoken through `langchain-groq`.
MODE_GROQ: Final = "groq"
#: Any other OpenAI-compatible `/chat/completions` endpoint (`base_url` required).
MODE_OPENAI_COMPATIBLE: Final = "openai_compatible"

Mode = Literal["off", "groq", "openai_compatible"]

#: The three accepted mode names, in the order `describe()` speaks them.
MODES: Final[tuple[str, ...]] = (MODE_OFF, MODE_GROQ, MODE_OPENAI_COMPATIBLE)

ENV_MODE: Final = "CLAIMGUARD_AI_MODE"
ENV_API_KEY: Final = "CLAIMGUARD_AI_API_KEY"
ENV_BASE_URL: Final = "CLAIMGUARD_AI_BASE_URL"
ENV_MODEL: Final = "CLAIMGUARD_AI_MODEL"
ENV_TIMEOUT: Final = "CLAIMGUARD_AI_TIMEOUT"
ENV_MAX_TOKENS: Final = "CLAIMGUARD_AI_MAX_TOKENS"

#: Older names, kept so an already-deployed `.env` keeps working: they are read
#: only when the documented name above is absent, so the newer contract always
#: wins. Both spellings are accepted; neither is ever logged.
ENV_GROQ_API_KEY: Final = "CLAIMGUARD_AI_GROQ_API_KEY"
ENV_GROQ_BASE_URL: Final = "CLAIMGUARD_AI_GROQ_BASE_URL"

#: Groq's OpenAI-compatible base URL, used when `mode=groq` names no other one.
GROQ_BASE_URL: Final = "https://api.groq.com/openai/v1"

#: The default model. Groq serves it; the prompt asks for a JSON object and the
#: verifier, not the model's size, is what makes an answer trustworthy.
DEFAULT_MODEL: Final = "qwen/qwen3.8-27b"
#: Long enough for one JSON answer, short enough that a hung endpoint cannot hold
#: a reviewer's request open.
DEFAULT_TIMEOUT_SECONDS: Final = 30.0
#: The five keys, two short paragraphs of text: a small ceiling that also stops a
#: runaway model from spending the reviewer's latency budget.
DEFAULT_MAX_TOKENS: Final = 700


@dataclass(frozen=True)
class AssistantSettings:
    """Which model, if any, may draft an answer — and how long it may take.

    Frozen because it is passed into the graph's state: a run must not be able to
    change its own permissions mid-flight.
    """

    mode: Mode = MODE_OFF
    model: str = DEFAULT_MODEL
    #: Empty means "not configured"; `mode='groq'` fills it with :data:`GROQ_BASE_URL`.
    base_url: str = ""
    #: The secret itself. Never rendered by :meth:`describe`, never stored in an
    #: answer, never written to a log.
    api_key: str | None = None
    timeout: float = DEFAULT_TIMEOUT_SECONDS
    max_tokens: int = DEFAULT_MAX_TOKENS
    #: What the environment actually said, so an unrecognised value can be
    #: reported as unrecognised instead of silently becoming `off`. The raw text
    #: is NOT echoed by `describe()`: it comes from the environment and is not
    #: safe to copy into a log.
    declared_mode: str = MODE_OFF

    @property
    def enabled(self) -> bool:
        """True only when a model could really be reached and is permitted to be.

        All three of mode, key and base URL must resolve: a mode without a key
        would fail at request time (and, worse, might be retried), so it counts
        as disabled and the reviewer gets the deterministic answer immediately.
        """
        return (
            self.mode != MODE_OFF
            and bool(self.model.strip())
            and bool(self.base_url.strip())
            and bool(self.api_key)
        )

    @property
    def model_version(self) -> str:
        """The provenance string recorded on a turn, e.g. ``groq:qwen/qwen3.8-27b``.

        `'none'` when no model may run, so a reader can tell "no model was
        configured" from "a model was configured and its draft was refused".
        """
        if not self.enabled:
            return "none"
        return f"{self.mode}:{self.model}"

    def describe(self) -> str:
        """A one-line, key-free summary for logs, `/v1/ai/status` and turn reasons."""
        parts = [
            f"assistant {'enabled' if self.enabled else 'disabled'}",
            f"mode={self.mode}",
            f"model={self.model}",
            f"base_url={self.base_url or '(unset)'}",
            f"key={'present' if self.api_key else 'absent'}",
            f"timeout={self.timeout:g}s",
            f"max_tokens={self.max_tokens}",
        ]
        if self.declared_mode not in MODES:
            parts.append(f"(the declared mode is not one of {list(MODES)}; using 'off')")
        if self.mode == MODE_OFF:
            parts.append(
                "(set CLAIMGUARD_AI_MODE and CLAIMGUARD_AI_API_KEY to let a model draft answers)"
            )
        return " ".join(parts)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AssistantSettings:
        """Build settings from ``env`` (``os.environ`` when ``None``).

        Never raises and never requires anything: an empty environment yields
        `mode='off'`, which is a working assistant.
        """
        source = _env_mapping() if env is None else env
        declared = (source.get(ENV_MODE) or "").strip()
        mode = _read_mode(declared)
        api_key = _first(source, ENV_API_KEY, ENV_GROQ_API_KEY)
        base_url = _first(source, ENV_BASE_URL, ENV_GROQ_BASE_URL)
        if mode == MODE_GROQ and not base_url:
            base_url = GROQ_BASE_URL
        return cls(
            mode=mode,
            model=_first(source, ENV_MODEL) or DEFAULT_MODEL,
            base_url=base_url,
            api_key=api_key,
            timeout=_positive_float(source.get(ENV_TIMEOUT), DEFAULT_TIMEOUT_SECONDS),
            max_tokens=_positive_int(source.get(ENV_MAX_TOKENS), DEFAULT_MAX_TOKENS),
            declared_mode=declared.casefold(),
        )


def _read_mode(declared: str) -> Mode:
    """The declared mode, or ``off`` when it is unrecognised (fail closed)."""
    normalised = declared.strip().casefold()
    if normalised == MODE_GROQ:
        return MODE_GROQ
    if normalised in (MODE_OPENAI_COMPATIBLE, "openai", "compatible"):
        return MODE_OPENAI_COMPATIBLE
    return MODE_OFF


def _first(source: Mapping[str, str], *names: str) -> str:
    """The first non-blank value among ``names`` (the documented name wins)."""
    for name in names:
        value = (source.get(name) or "").strip()
        if value:
            return value
    return ""


def _env_mapping() -> Mapping[str, str]:
    """The process environment as a plain mapping (imported lazily, never logged)."""
    import os

    return os.environ


def _positive_float(raw: str | None, default: float) -> float:
    """``raw`` as a positive finite float, else ``default`` (a bad value degrades)."""
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 and math.isfinite(value) else default


def _positive_int(raw: str | None, default: int) -> int:
    """``raw`` as a positive int, else ``default`` (a bad value degrades)."""
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default

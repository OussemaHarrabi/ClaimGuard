"""Environment configuration for the advisory judge.

Four variables, all read from the environment and never from a file this module
writes:

======================  =============================  =========================
Variable                Meaning                        Default
======================  =============================  =========================
``..._API_KEY``         TypeSafe bearer token          *(unset → judge off)*
``..._BASE_URL``        API origin                     ``https://api.typesafe.ai``
``CLAIMGUARD_JEV_MODEL`` model name                     ``jev-latest``
``..._TIMEOUT_SECONDS`` per-request timeout             ``30``
======================  =============================  =========================

Absence is not an error. With no key the judge is *disabled*: the system behaves
exactly as it does without this layer, and nothing is ever sent anywhere. The
key is a secret: it is never written to a file, never logged, and
:meth:`JudgeSettings.describe` and :meth:`JudgeSettings.redact` exist so that the
only two places that could leak it cannot.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

#: The variable that enables the judge. Unset or blank means "disabled".
ENV_API_KEY: Final = "CLAIMGUARD_TYPESAFE_API_KEY"
ENV_BASE_URL: Final = "CLAIMGUARD_TYPESAFE_BASE_URL"
ENV_MODEL: Final = "CLAIMGUARD_JEV_MODEL"
ENV_TIMEOUT: Final = "CLAIMGUARD_JEV_TIMEOUT_SECONDS"

DEFAULT_BASE_URL: Final = "https://api.typesafe.ai"
#: The vendor is in early access: this default is a *placeholder* until
#: ``judge probe`` lists the models the account can actually see.
DEFAULT_MODEL: Final = "jev-latest"
DEFAULT_TIMEOUT: Final = 30.0

#: What :meth:`JudgeSettings.describe` prints instead of the credential itself.
REDACTED: Final = "<redacted>"
KEY_SET: Final = "set"
KEY_ABSENT: Final = "unset"


def _env_mapping() -> Mapping[str, str]:
    """The process environment as a plain mapping (imported lazily, never logged)."""
    import os

    return os.environ


def _positive_float(raw: str | None, default: float) -> float:
    """Parse a positive finite float, falling back to ``default`` when unusable."""
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 and math.isfinite(value) else default


@dataclass(frozen=True)
class JudgeSettings:
    """Where the judge would talk to, and how long it is allowed to take.

    Construction performs no I/O and reads no network: a settings object is
    inert configuration, and ``api_key is None`` is the disabled state.
    """

    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    api_key: str | None = field(default=None, repr=False)
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> JudgeSettings:
        """Build settings from ``env`` (default: the process environment).

        A blank value is treated as unset, so an ``.env`` template with empty
        assignments cannot half-configure the judge.
        """
        source = _env_mapping() if env is None else env
        return cls(
            base_url=(source.get(ENV_BASE_URL) or "").strip() or DEFAULT_BASE_URL,
            model=(source.get(ENV_MODEL) or "").strip() or DEFAULT_MODEL,
            api_key=(source.get(ENV_API_KEY) or "").strip() or None,
            timeout=_positive_float(source.get(ENV_TIMEOUT), DEFAULT_TIMEOUT),
        )

    def configured(self) -> bool:
        """True only when an API key is present — the judge's one enabling switch."""
        return bool(self.api_key)

    def endpoint(self, path: str) -> str:
        """The absolute URL of one API path (``/v1/systemone``)."""
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    def headers(self, *, json_body: bool) -> dict[str, str]:
        """Request headers, including the bearer token when one is configured."""
        headers = {"Accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def describe(self) -> str:
        """A one-line, safe description — the key is reported as present or absent."""
        state = KEY_SET if self.configured() else KEY_ABSENT
        return (
            f"judge={'enabled' if self.configured() else 'disabled'} "
            f"model={self.model} base_url={self.base_url} "
            f"timeout={self.timeout:g}s api_key={state}"
        )

    def redact(self, text: str) -> str:
        """Replace the credential with :data:`REDACTED` in any text we may print.

        Every message this layer produces passes through here before it is
        logged, written or raised, so a key that somehow reached an exception
        message cannot reach a log file.
        """
        if not self.api_key:
            return text
        return text.replace(self.api_key, REDACTED)

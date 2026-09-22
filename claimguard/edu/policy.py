"""Rule-directory catalogues and rule metadata (the pack's ``rules/`` folder).

Loaded once per run from ``--rules-dir``:

*   ``policies.json``      — policy profiles (currency, window, network, limits)
*   ``services.json``      — the fictional service catalogue (R011)
*   ``providers.json``     — informational provider directory
*   ``diagnoses.json``     — informational teaching diagnosis codes
*   ``rules.json``         — per-rule severity, corrective action, version, source

Two contract points that the rulebook makes explicit and that this module
preserves (docs/04_Rulebook.md:11 and 15):

*   an unknown ``policy_id`` means NO matching policy was supplied — it is not
    proof of non-coverage and must never be replaced by an invented default.
    :meth:`RuleContext.policy` therefore returns ``None``.
*   rule severity, corrective action, version and source always come from the
    pack manifest, never from hardcoded strings in rule code
    (``schemas/result.schema.json`` requires ``rule_source`` =
    ``fictional-rulebook/<RULE_ID>@1.0.0``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from claimguard.edu.envelope import RULE_IDS, RULE_VERSION, Severity

ModelT = TypeVar("ModelT", bound=BaseModel)

POLICY_FILE: Final = "policies.json"
SERVICE_FILE: Final = "services.json"
PROVIDER_FILE: Final = "providers.json"
DIAGNOSIS_FILE: Final = "diagnoses.json"
RULE_FILE: Final = "rules.json"


class RuleDirError(ValueError):
    """The rule directory is missing or does not match the pack contract."""


class Service(BaseModel):
    """One entry of ``rules/services.json`` (the fictional catalogue of R011)."""

    description: str | None = None
    base_price: int | float | None = None
    max_price: int | float | None = None
    max_quantity: int | float | None = None


class Provider(BaseModel):
    """One entry of ``rules/providers.json``."""

    provider_id: str
    display: str | None = None


class Diagnosis(BaseModel):
    """One entry of ``rules/diagnoses.json`` — presence only, no clinical meaning."""

    model_config = ConfigDict(extra="ignore")

    code: str
    display: str | None = None


class Policy(BaseModel):
    """One policy profile of ``rules/policies.json``.

    ``max_unit_price`` / ``max_quantity_per_line`` live here — R013 uses these
    limits, NOT the ``services.json`` prices (docs/04_Rulebook.md:136-142 and 19-38).
    """

    policy_id: str
    version: str | None = None
    payer_id: str | None = None
    currency: str
    submission_window_days: int
    allowed_providers: list[str]
    auth_required_services: list[str]
    required_documents: dict[str, str]
    max_unit_price: dict[str, int | float]
    max_quantity_per_line: dict[str, int | float]

    def auth_required(self, service_code: Any) -> bool:
        """True when ``service_code`` requires an authorization reference (R008/R009)."""
        return service_code in self.auth_required_services

    def required_document(self, service_code: Any) -> str | None:
        """Required attachment type for ``service_code``, or None (R010)."""
        return self.required_documents.get(service_code) if isinstance(service_code, str) else None

    def max_price_for(self, service_code: Any) -> int | float | None:
        """Fictional maximum unit price, or None when the code is not priced."""
        return self.max_unit_price.get(service_code) if isinstance(service_code, str) else None

    def max_quantity_for(self, service_code: Any) -> int | float | None:
        """Fictional maximum quantity per line, or None when the code is not priced."""
        return (
            self.max_quantity_per_line.get(service_code) if isinstance(service_code, str) else None
        )


class RuleMeta(BaseModel):
    """One entry of ``rules/rules.json``: the authoritative rule manifest."""

    rule_id: str
    title: str
    severity: Severity
    logic: str
    corrective_action: str
    version: str
    source: str


@dataclass(frozen=True)
class RuleContext:
    """Everything a rule needs beyond the claim itself."""

    policies: Mapping[str, Policy]
    services: Mapping[str, Service]
    providers: Mapping[str, Provider]
    diagnoses: Mapping[str, Diagnosis]
    rules: Mapping[str, RuleMeta]

    @classmethod
    def from_rules_dir(cls, rules_dir: str | Path) -> RuleContext:
        """Load every catalogue from ``rules_dir`` (the pack's ``rules/``)."""
        directory = Path(rules_dir)
        if not directory.is_dir():
            raise RuleDirError(f"Rule directory not found: {directory}")
        policies = _load_model_dict(directory / POLICY_FILE, Policy)
        services = _load_model_dict(directory / SERVICE_FILE, Service)
        providers = _load_model_list(directory / PROVIDER_FILE, Provider, "provider_id")
        diagnoses = _load_model_list(directory / DIAGNOSIS_FILE, Diagnosis, "code")
        rules_raw = _load_json(directory / RULE_FILE)
        if not isinstance(rules_raw, list):
            raise RuleDirError(f"{RULE_FILE} must contain a list of rule records")
        rules: dict[str, RuleMeta] = {}
        for entry in cast(list[object], rules_raw):
            manifest = RuleMeta.model_validate(entry)
            rules[manifest.rule_id] = manifest
        missing = [rule_id for rule_id in RULE_IDS if rule_id not in rules]
        if missing:
            raise RuleDirError(f"{RULE_FILE} is missing rule ids: {', '.join(missing)}")
        for rule_id, meta in rules.items():
            if meta.version != RULE_VERSION:
                raise RuleDirError(f"{rule_id} has unexpected version {meta.version!r}")
            if meta.source != f"fictional-rulebook/{rule_id}@{meta.version}":
                raise RuleDirError(f"{rule_id} has unexpected source {meta.source!r}")
        return cls(
            policies=policies,
            services=services,
            providers=providers,
            diagnoses=diagnoses,
            rules=rules,
        )

    def policy(self, policy_id: Any) -> Policy | None:
        """Resolve ``policy_id``; an unknown id has no matching policy (never a default)."""
        if not isinstance(policy_id, str):
            return None
        return self.policies.get(policy_id)

    def rule(self, rule_id: str) -> RuleMeta:
        """Return the manifest metadata for ``rule_id`` (severity/action/source)."""
        meta = self.rules.get(rule_id)
        if meta is None:
            raise RuleDirError(f"No manifest entry for {rule_id}")
        return meta

    def service(self, service_code: Any) -> Service | None:
        """Return the catalogue entry for ``service_code``, or None when unknown."""
        if not service_code or not isinstance(service_code, str):
            return None
        return self.services.get(service_code)

    def knows_service(self, service_code: Any) -> bool:
        """True when ``service_code`` occurs in ``rules/services.json`` (R011)."""
        return (
            isinstance(service_code, str) and bool(service_code) and service_code in self.services
        )

    def provider(self, provider_id: Any) -> Provider | None:
        """Return the directory entry for ``provider_id``, or None when unlisted."""
        if not isinstance(provider_id, str):
            return None
        return self.providers.get(provider_id)

    def diagnosis(self, code: Any) -> Diagnosis | None:
        """Return the teaching diagnosis entry for ``code``, or None."""
        if not isinstance(code, str):
            return None
        return self.diagnoses.get(code)

    def unknown_service_lines(self, lines: Sequence[Mapping[str, Any]]) -> list[int]:
        """Indices of lines whose service_code is present but not in the catalogue.

        An unknown code could require authorization or documentation, so rules
        R008-R010 must abstain rather than assume it does not
        (docs/04_Rulebook.md:96-118).
        """
        return [
            index
            for index, line in enumerate(lines)
            if isinstance(line.get("service_code"), str)
            and line["service_code"]
            and line["service_code"] not in self.services
        ]


def _load_json(path: Path) -> Any:
    if not path.is_file():
        raise RuleDirError(f"Missing rule file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuleDirError(f"Invalid JSON in {path}: {exc}") from exc


def _load_model_dict(path: Path, model: type[ModelT]) -> dict[str, ModelT]:
    """Load an id-keyed catalogue file into validated models."""
    raw = _load_json(path)
    if not isinstance(raw, dict):
        raise RuleDirError(f"{path.name} must contain an object keyed by id")
    entries = cast(dict[str, Any], raw)
    return {str(key): model.model_validate(value) for key, value in entries.items()}


def _load_model_list(path: Path, model: type[ModelT], key: str) -> dict[str, ModelT]:
    """Load a list catalogue file into validated models keyed by ``key``."""
    raw = _load_json(path)
    if not isinstance(raw, list):
        raise RuleDirError(f"{path.name} must contain a list of records")
    records: dict[str, ModelT] = {}
    for entry in cast(list[object], raw):
        record = model.model_validate(entry)
        records[str(getattr(record, key))] = record
    return records

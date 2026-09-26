"""One FHIR mapping example: a real collection Bundle projected onto the envelope.

Usage (from the repository root)::

    uv run python scripts/fhir_example.py
    uv run python scripts/fhir_example.py --claim-id CG-F5F2411AC3AD --split development

Pack Required MVP behaviour 1 asks for the normalized JSONL to be ingested **and** for one
FHIR mapping example to be demonstrated (``<pack>/docs/01_Challenge_Brief.md``). The
projection itself lives in :mod:`claimguard.edu.intake.fhir_source`; this script is the
demonstration a reviewer can run and read: it takes one real bundle, projects it, and
prints the resource inventory, the envelope fields recovered (with their values), the
exact fields the bundle cannot supply, and what those gaps mean for the 15 checks.

What it prints is a transcript, not a verdict. Nothing here approves, denies, prices or
judges a claim: the projection reports which envelope fields the bundle carries and
stops there. No network client and no database session is constructed; the JSONL is read
from disk.

Three facts the transcript states because the mentor pack states them
(``<pack>/docs/11_FHIR_Orientation.md``, "Deliberate limitations"):

* full authorization details, policy limits, notes and some source metadata stay in the
  normalized sidecar — **FHIR files alone are insufficient to reproduce all 15 checks**;
* **no reverse adapter is included**, and none is invented here;
* keep the **normalized JSONL envelope as the benchmark input**, which is why a partial
  projection must never be laundered into a scored envelope.

That last point is enforced, not asserted: the script runs the transport contract's own
validator over the projection and prints the refusal it gets. The result is an
integration artifact — read and reviewed, never fed to the engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import textwrap
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, cast

REPO_ROOT: Final = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR: Final = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from claimguard.edu.envelope import (  # noqa: E402
    ENVELOPE_KEYS,
    RULE_IDS,
    TransportError,
    validate_transport,
)
from claimguard.edu.intake.fhir_source import (  # noqa: E402
    ALL_FIELD_PATHS,
    SUPPORTED_FIELDS,
    UNSUPPORTED_FIELDS,
    FhirIntakeError,
    FhirProjection,
    project_bundle,
    read_bundles,
)

from edu_conformance import (  # noqa: E402  (sibling module; sys.path fixed above)
    ConformanceError,
    find_pack_root,
)

DEFAULT_SPLIT: Final = "development"

#: docs/11_FHIR_Orientation.md, "Deliberate limitations" — quoted verbatim in the
#: transcript so the demonstration carries the pack's own words, not our paraphrase.
PACK_LIMITATION: Final = (
    "Full authorization details, policy limits, notes and some source metadata remain in "
    "the normalized sidecar; FHIR files alone are insufficient to reproduce all 15 checks. "
    "No reverse adapter is included."
)

#: The envelope containers, in contract order (``coverage`` is one object, the rest arrays).
CONTAINERS: Final = ("coverage", "lines", "authorizations", "attachments")

#: Column width of an envelope leaf path in the recovered-fields section.
_PATH_WIDTH: Final = 34


class ExampleError(RuntimeError):
    """The example cannot be produced: the pack, the split or the bundle is unusable."""


@dataclass(frozen=True)
class RuleInputs:
    """One check and the envelope leaf paths it reads (``*`` stands for one array element).

    Declared here rather than in the engine because ``claimguard/edu/rules/**`` owns the
    rules and this script only reports which of their *inputs* a bundle can carry. Each
    list was read off the rule implementation (``claimguard/edu/rules/r001_r007.py``,
    ``r008_r015.py``) and off the contract in ``rules/rules.json``; the ``inputs`` paths
    are validated against :data:`ALL_FIELD_PATHS` at run time, so a typo fails loudly
    instead of passing as "supported".
    """

    rule_id: str
    inputs: tuple[str, ...]


#: What each of the 15 checks reads from the claim envelope. The rule-directory
#: catalogues (policies, services, providers, diagnoses) are separate rule inputs, not
#: envelope fields: they are delivered with the pack and are unchanged by the projection,
#: so ``/policy_id`` is all a policy-dependent check needs from the bundle.
RULE_INPUTS: Final[tuple[RuleInputs, ...]] = (
    RuleInputs(
        "R001",
        (
            "/invoice_number",
            "/member_id",
            "/diagnosis_code",
            "/lines/*/service_date",
            "/lines/*/service_code",
            "/lines/*/quantity",
            "/lines/*/unit_price",
            "/lines/*/net_amount",
        ),
    ),
    RuleInputs("R002", ("/submission_date", "/lines/*/service_date")),
    RuleInputs(
        "R003",
        (
            "/coverage/status",
            "/coverage/start_date",
            "/coverage/end_date",
            "/lines/*/service_date",
        ),
    ),
    RuleInputs(
        "R004",
        (
            "/patient_id",
            "/member_id",
            "/coverage/beneficiary_patient_id",
            "/coverage/member_id",
        ),
    ),
    RuleInputs("R005", ("/provider_id", "/policy_id")),
    RuleInputs(
        "R006",
        ("/lines/*/service_code", "/lines/*/service_date", "/lines/*/modifier"),
    ),
    RuleInputs(
        "R007",
        ("/lines/*/quantity", "/lines/*/unit_price", "/lines/*/net_amount"),
    ),
    RuleInputs(
        "R008",
        ("/policy_id", "/lines/*/service_code", "/lines/*/authorization_id"),
    ),
    RuleInputs(
        "R009",
        (
            "/policy_id",
            "/lines/*/service_code",
            "/lines/*/service_date",
            "/lines/*/authorization_id",
            "/authorizations/*/authorization_id",
            "/authorizations/*/patient_id",
            "/authorizations/*/service_code",
            "/authorizations/*/status",
            "/authorizations/*/valid_from",
            "/authorizations/*/valid_to",
            "/authorizations/*/max_quantity",
        ),
    ),
    RuleInputs(
        "R010",
        (
            "/policy_id",
            "/lines/*/service_code",
            "/lines/*/service_date",
            "/attachments/*/type",
            "/attachments/*/patient_id",
            "/attachments/*/service_code",
            "/attachments/*/service_date",
            "/attachments/*/document_status",
        ),
    ),
    RuleInputs("R011", ("/lines/*/service_code",)),
    RuleInputs("R012", ("/total_amount", "/lines/*/net_amount")),
    RuleInputs(
        "R013",
        (
            "/policy_id",
            "/lines/*/service_code",
            "/lines/*/quantity",
            "/lines/*/unit_price",
        ),
    ),
    RuleInputs("R014", ("/policy_id", "/submission_date", "/lines/*/service_date")),
    RuleInputs("R015", ("/policy_id", "/currency")),
)

#: The envelope leaf paths the pack's FHIR bundles cannot supply, as one set.
_UNSUPPORTED_PATHS: Final = frozenset(field.path for field in UNSUPPORTED_FIELDS)

#: ``path`` -> the module's reason, so the transcript never re-writes it by hand.
_UNSUPPORTED_REASONS: Final = {field.path: field.reason for field in UNSUPPORTED_FIELDS}


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def _emit(text: str = "") -> None:
    sys.stdout.write(text + "\n")


def _display(path: Path) -> str:
    """A path as the repository sees it: repo-relative when it lives inside the repo."""
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _literal(value: Any) -> str:
    """One scalar as JSON, with a :class:`~decimal.Decimal` written as its exact literal.

    The money leaves are ``Decimal`` (``claimguard.edu.intake.dump_envelope``'s rule);
    routing them through ``json.dumps`` would raise, and through ``float`` would silently
    re-spell the value.
    """
    return str(value) if isinstance(value, Decimal) else json.dumps(value, ensure_ascii=False)


def _wrapped(text: str, indent: str = "      ") -> list[str]:
    return textwrap.wrap(text, width=98, initial_indent=indent, subsequent_indent=indent) or [
        indent
    ]


def _leaves(node: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Every scalar in ``node`` as ``(path, value)``, in contract order."""
    for key, value in node.items():
        path = f"{prefix}/{key}"
        if isinstance(value, Mapping):
            yield from _leaves(cast("Mapping[str, Any]", value), path)
        elif isinstance(value, Sequence) and not isinstance(value, str):
            for index, item in enumerate(cast("Sequence[Any]", value)):
                if isinstance(item, Mapping):
                    yield from _leaves(cast("Mapping[str, Any]", item), f"{path}/{index}")
                else:
                    yield f"{path}/{index}", item
        else:
            yield path, value


def blocked_paths(rule: RuleInputs) -> tuple[str, ...]:
    """The paths of ``rule`` the projection cannot supply — the reason it is not answerable."""
    return tuple(path for path in rule.inputs if path in _UNSUPPORTED_PATHS)


def unknown_input_paths() -> tuple[str, ...]:
    """Declared rule inputs that are not envelope leaf paths at all (a table typo)."""
    known = frozenset(ALL_FIELD_PATHS)
    return tuple(path for rule in RULE_INPUTS for path in rule.inputs if path not in known)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _rule_titles(catalogue: Path) -> dict[str, str]:
    """Rule id -> title, from the pack's authoritative ``rules/rules.json``."""
    if not catalogue.is_file():
        raise ExampleError(f"the rule catalogue is missing: {catalogue}")
    parsed: Any = json.loads(catalogue.read_text(encoding="utf-8"))
    if not isinstance(parsed, list):
        raise ExampleError(f"{catalogue}: expected a JSON array of rules")
    titles: dict[str, str] = {}
    for entry in cast("list[Any]", parsed):
        if not isinstance(entry, Mapping):
            continue
        record = cast("Mapping[str, Any]", entry)
        rule_id = record.get("rule_id")
        title = record.get("title")
        if isinstance(rule_id, str) and isinstance(title, str):
            titles[rule_id] = title
    missing = [rule_id for rule_id in RULE_IDS if rule_id not in titles]
    if missing:
        raise ExampleError(f"{catalogue}: no title for {', '.join(missing)}")
    return titles


def _select_bundle(
    path: Path, claim_id: str | None
) -> tuple[int, int, dict[str, Any], FhirProjection]:
    """The bundle to demonstrate, its 1-based object index, the file's object count, its projection.

    With ``claim_id`` the bundle is the one whose Claim carries that id. Without it the
    first bundle whose Claim carries an attachment is used, because an attachment is the
    most interesting thing a projection can show and the supportable/metadata split of an
    attachment is exactly where the bundle runs out of information.
    """
    if not path.is_file():
        raise ExampleError(f"the split's FHIR bundle file is missing: {_display(path)}")
    bundles = read_bundles(path)
    if not bundles:
        raise ExampleError(f"{_display(path)}: contains no bundles")
    failures: list[str] = []
    for index, bundle in enumerate(bundles, start=1):
        try:
            projection = project_bundle(bundle)
        except FhirIntakeError as exc:
            failures.append(f"object {index}: {exc}")
            continue
        if claim_id is not None:
            if projection.envelope.get("claim_id") == claim_id:
                return index, len(bundles), bundle, projection
        elif projection.envelope.get("attachments"):
            return index, len(bundles), bundle, projection
    if claim_id is not None:
        raise ExampleError(f"no bundle in {_display(path)} carries Claim.id {claim_id!r}")
    detail = (
        f"; {len(failures)} object(s) could not be projected ({failures[0]})" if failures else ""
    )
    raise ExampleError(f"no bundle in {_display(path)} carries an attachment{detail}")


# ---------------------------------------------------------------------------
# Transcript sections
# ---------------------------------------------------------------------------


def _header(
    pack_root: Path,
    split: str,
    path: Path,
    index: int,
    total: int,
    requested: str | None,
    selected_id: str,
) -> list[str]:
    """The frame: what was read, from where, and what was deliberately not touched."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    catalogue = pack_root / "rules" / "rules.json"
    catalogue_digest = hashlib.sha256(catalogue.read_bytes()).hexdigest()
    selected = (
        "first bundle whose Claim carries an attachment; --claim-id names another"
        if requested is None
        else f"--claim-id {requested}"
    )
    return [
        "ClaimGuard AI — one FHIR mapping example (pack Required MVP behaviour 1)",
        "======================================================================",
        "Synthetic teaching data. Nothing here is submitted to a payer, and no claim is",
        "approved, denied or judged: the system reviews, it does not adjudicate.",
        "",
        f"pack root      : {_display(pack_root)}",
        f"split          : {split}",
        f"source         : {_display(path)}",
        f"source sha256  : {digest}",
        f"bundles        : {total} bundle(s), one JSON object per line",
        f"demonstrating  : object {index} of {total}, Claim.id {selected_id}",
        f"selection      : {selected}",
        f"rules.json     : {_display(catalogue)} sha256 {catalogue_digest}",
        "network        : none used — the JSONL is read from disk; no socket, no request is made",
        "database       : none used — no connection or session is opened; no ORM is imported",
        "",
        'the pack\'s own words (docs/11_FHIR_Orientation.md, "Deliberate limitations"):',
        *_wrapped(f"“{PACK_LIMITATION}”"),
    ]


def _inventory(bundle: Mapping[str, Any]) -> list[str]:
    """What the bundle actually contains, in entry order."""
    entries = bundle.get("entry")
    rows = cast("list[Any]", entries) if isinstance(entries, list) else []
    lines = ["", "[1/6] bundle resource inventory (entry order)"]
    counts: Counter[str] = Counter()
    for position, entry in enumerate(rows):
        resource: Any = None
        if isinstance(entry, Mapping):
            resource = cast("Mapping[str, Any]", entry).get("resource")
        if not isinstance(resource, Mapping):
            lines.append(f"  {position:>3}  <entry carries no resource>")
            continue
        record = cast("Mapping[str, Any]", resource)
        kind = str(record.get("resourceType", "<untyped>"))
        counts[kind] += 1
        lines.append(f"  {position:>3}  {kind:<19} {record.get('id', '')}")
    summary = ", ".join(f"{kind} {count}" for kind, count in sorted(counts.items()))
    lines.append(f"  {sum(counts.values())} resource(s): {summary}")
    return lines


def _recovered(projection: FhirProjection) -> list[str]:
    """The envelope fields the bundle supplies — with the exact value recovered for each."""
    leaves = list(_leaves(projection.envelope))
    lines = [
        "",
        "[2/6] envelope fields the projection recovers from this bundle",
        f"      the projection can supply {len(SUPPORTED_FIELDS)} of the "
        f"{len(ALL_FIELD_PATHS)} contract leaf paths; this bundle carries {len(leaves)} of them",
    ]
    for path, value in leaves:
        lines.append(f"  {path:<{_PATH_WIDTH}} = {_literal(value)}")
    for key in CONTAINERS:
        value = projection.envelope.get(key)
        if isinstance(value, list):
            elements = cast("list[Any]", value)
            lines.append(f"  /{key:<{_PATH_WIDTH - 1}} = {len(elements)} element(s)")
        elif isinstance(value, Mapping):
            lines.append(f"  /{key:<{_PATH_WIDTH - 1}} = object")
    lines.append(
        "  mapping table: claimguard/edu/intake/fhir_source.py (module docstring), verified"
    )
    lines.append("  bundle by bundle in tests/edu_intake/test_fhir_source.py")
    return lines


def _unsupported() -> list[str]:
    """The gap, straight from the module: every path and the module's own reason.

    A reason shared by consecutive paths (the six sidecar-only authorisation fields, for
    instance) is printed once, so the section stays a report and not a repetition.
    """
    lines = [
        "",
        f"[3/6] envelope fields the projection CANNOT supply ({len(UNSUPPORTED_FIELDS)} of "
        f"{len(ALL_FIELD_PATHS)} contract leaf paths)",
        "      every path the module declares, with its own reason; a reason shared by",
        "      consecutive paths is stated once",
    ]
    previous: str | None = None
    for field in UNSUPPORTED_FIELDS:
        marker = "" if field.reason != previous else "  (same reason as above)"
        lines.append(f"  {field.path}{marker}")
        if field.reason != previous:
            lines.extend(_wrapped(field.reason))
        previous = field.reason
    return lines


def _rule_impact(titles: Mapping[str, str]) -> list[str]:
    """Which of the 15 checks the recovered fields can answer, and which they cannot."""
    not_answerable = [rule for rule in RULE_INPUTS if blocked_paths(rule)]
    answerable = [rule for rule in RULE_INPUTS if not blocked_paths(rule)]
    lines = [
        "",
        "[4/6] what the gaps mean for the 15 checks",
        "      a check counts as answerable here only if every envelope leaf path it reads is",
        "      one the bundle supplies. The rule-directory catalogues are separate rule inputs,",
        "      unchanged by the projection, so /policy_id is enough for a policy-dependent check.",
    ]
    for rule in answerable:
        lines.append(
            f"  {rule.rule_id}  yes  {titles[rule.rule_id]:<44} "
            f"reads {len(rule.inputs)} envelope path(s)"
        )
    for rule in not_answerable:
        blocked = blocked_paths(rule)
        lines.append(
            f"  {rule.rule_id}  NO   {titles[rule.rule_id]:<44} blocked by {len(blocked)} path(s)"
        )
        for path in blocked:
            lines.append(f"           {path}")
        lines.append("         and the projection does not carry them because:")
        for reason in dict.fromkeys(_UNSUPPORTED_REASONS[path] for path in blocked):
            lines.extend(_wrapped(reason, indent="           "))
    names = ", ".join(rule.rule_id for rule in not_answerable)
    lines.append(
        f"  answerable {len(answerable)} of {len(RULE_INPUTS)}; "
        f"not answerable {len(not_answerable)} ({names})"
    )
    return lines


def _contract_refusal(projection: FhirProjection) -> list[str]:
    """Prove the projection is not engine input, using the contract's own validator."""
    missing = [key for key in ENVELOPE_KEYS if key not in projection.envelope]
    nested = [field.path for field in UNSUPPORTED_FIELDS if field.path.count("/") > 1]
    try:
        validate_transport(projection.envelope)
        verdict = "ACCEPTED (unexpected: the projection is documented as partial)"
    except TransportError as exc:
        verdict = f"TransportError: {exc}"
    lines = [
        "",
        "[5/6] why this projection is not engine input",
        "      the transport contract requires exactly the 17 envelope keys and, inside them,",
        f"      every child key. This projection omits {len(missing)} key(s) and "
        f"{len(nested)} nested field(s):",
        f"        keys   : {', '.join(missing)}",
        "        nested : " + (nested[0] if nested else "none"),
    ]
    lines.extend(f"                 {path}" for path in nested[1:])
    lines.extend(
        [
            f"      the contract's own validator says: {verdict}",
            "      so it is an integration artifact: read and reviewed, never scored. The",
            "      engine's input stays the normalized JSONL envelope.",
        ]
    )
    return lines


def _limits() -> list[str]:
    """What the demonstration does not claim."""
    return [
        "",
        "[6/6] what this example does not claim",
        "  - FHIR alone cannot reproduce all 15 checks. That is the pack's statement, not our",
        '    finding: docs/11_FHIR_Orientation.md, "Deliberate limitations" (quoted above).',
        "  - No reverse adapter was written, and none is needed: the normalized JSONL envelope",
        "    is the benchmark input, and FHIR is an integration exercise beside it.",
        '  - "answerable" means every field the check reads is supplied by the bundle. It does',
        "    not promise the check will not abstain for another reason (an unknown service code,",
        "    a policy the catalogue does not list).",
        "  - R009 and R010 cannot be completed from the bundle: an authorization record's",
        "    status, dates, service, patient and quantity, and an attachment's service code and",
        "    document status, live in the sidecar. Nothing here guesses them.",
        "  - The recovered fields mirror the bundle verbatim. A reference is read as written, a",
        "    code stays in the code space it was written in, and attachment text is untrusted",
        "    data that is never parsed into a field value.",
        "  - The run is a file read, a projection and a print: no socket is opened, no database",
        "    connection is opened, and no model is called.",
        "  - The data is synthetic. No claim is submitted to a payer, and no status printed by",
        "    this script is a payment approval — no status is printed at all.",
        "",
        "  reproduce: uv run python scripts/fhir_example.py",
        "             uv run pytest tests/edu_intake -q",
    ]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def transcript(pack_root: Path, split: str, claim_id: str | None) -> list[str]:
    """The whole transcript, as lines, for one bundle of one split."""
    unknown = unknown_input_paths()
    if unknown:
        raise ExampleError(f"declared rule inputs are not envelope paths: {', '.join(unknown)}")
    path = pack_root / "data" / split / "fhir_bundles.jsonl"
    index, total, bundle, projection = _select_bundle(path, claim_id)
    selected_id = str(projection.envelope.get("claim_id"))
    titles = _rule_titles(pack_root / "rules" / "rules.json")
    return (
        _header(pack_root, split, path, index, total, claim_id, selected_id)
        + _inventory(bundle)
        + _recovered(projection)
        + _unsupported()
        + _rule_impact(titles)
        + _contract_refusal(projection)
        + _limits()
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Project one real mentor-pack FHIR collection Bundle onto the claim envelope and "
            "print the recovered fields, the unsupported fields and their effect on the 15 checks."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--claim-id",
        default=None,
        help=(
            "Claim.id to demonstrate; without it the first bundle whose Claim carries an "
            "attachment is used"
        ),
    )
    parser.add_argument("--split", default=DEFAULT_SPLIT, help="pack split to read bundles from")
    parser.add_argument("--pack-root", default=None, help="mentor pack root (auto-discovered)")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Print the transcript; return a process exit code (0 shown, 2 refused)."""
    args = parse_args(argv)
    explicit = Path(str(args.pack_root)) if args.pack_root else None
    try:
        pack_root = find_pack_root(explicit)
        lines = transcript(pack_root, str(args.split), cast("str | None", args.claim_id))
    except (ExampleError, ConformanceError, FhirIntakeError) as exc:
        _emit(f"fhir example refused: {exc}")
        return 2
    for line in lines:
        _emit(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

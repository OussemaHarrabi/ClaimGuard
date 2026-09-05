"""FHIR bundle reference resolution (ING-04).

WHY THIS FILE IS DISPROPORTIONATELY IMPORTANT
---------------------------------------------
Four rules depend on it — ENC-001, AUTH-004, DOC-004, ID-002. If a reference
silently fails to resolve, those rules either fail to fire or fire wrongly, and
the failure is invisible: a dangling reference looks identical to an absent one.

THE TRAP (07 §8 trap #1)
------------------------
The same resource can be addressed FIVE different ways in a FHIR bundle:

    "Patient/123"                          relative, typed
    "http://example.org/fhir/Patient/123"  absolute URL
    "urn:uuid:3a4b5c6d-..."                UUID
    "urn:oid:1.2.3.4.5"                    OID
    "#p1"                                  contained, INSIDE the resource

A resolver handling only one spelling breaks on real bundles. Two resources of
different types may share an id (`Patient/42` and `Claim/42`), so the index must
be keyed by (type, id) — never by id alone.

FAILURE POLICY
--------------
Resolution never raises. An unresolvable reference becomes a dangling entry that
the rules consume (ENC-001 fires on it). Crashing on a malformed claim would turn
our own quality gate into a denial of service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urlparse

_UUID_PREFIX = "urn:uuid:"
_OID_PREFIX = "urn:oid:"


@dataclass(frozen=True)
class IndexedResource:
    """A resource located in a bundle, with what is needed to cite it."""

    resource_type: str
    resource_id: str
    resource: dict[str, Any]
    entry_index: int | None = None
    full_url: str | None = None


@dataclass
class DanglingReference:
    """A reference that could not be resolved. This is a finding, not a crash."""

    raw_reference: str
    source_pointer: str
    reason: str


@dataclass
class ResolutionReport:
    """Outcome of indexing + resolving one bundle."""

    indexed_count: int = 0
    dangling: list[DanglingReference] = field(default_factory=lambda: [])

    @property
    def has_dangling(self) -> bool:
        return bool(self.dangling)


class BundleIndex:
    """Indexes a FHIR Bundle and resolves references against it.

    Two-pass by design (07 §8 trap #1): build the complete index first, then
    resolve. Single-pass resolution fails whenever a reference points forward to
    an entry that has not been seen yet — which is normal in real bundles.
    """

    def __init__(self, bundle: dict[str, Any]) -> None:
        self._by_type_id: dict[tuple[str, str], IndexedResource] = {}
        self._by_uuid: dict[str, IndexedResource] = {}
        self._by_oid: dict[str, IndexedResource] = {}
        self._contained: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._report = ResolutionReport()
        self._index_bundle(bundle)

    # ------------------------------------------------------------------
    # Indexing (pass 1)
    # ------------------------------------------------------------------

    def _index_bundle(self, bundle: Any) -> None:
        """Build every lookup table before any reference is resolved."""
        if not isinstance(bundle, dict):
            return

        b = cast(dict[str, Any], bundle)
        entries = b.get("entry")
        if not isinstance(entries, list):
            # A bare resource (not a bundle) is still indexable by its own id.
            self._index_resource(b, entry_index=None, full_url=None)
            return

        for i, entry in enumerate(cast(list[object], entries)):
            if not isinstance(entry, dict):
                continue
            e = cast(dict[str, Any], entry)
            resource = e.get("resource")
            if not isinstance(resource, dict):
                continue
            r = cast(dict[str, Any], resource)
            full_url = e.get("fullUrl")
            self._index_resource(
                r,
                entry_index=i,
                full_url=full_url if isinstance(full_url, str) else None,
            )

    def _index_resource(
        self, resource: dict[str, Any], entry_index: int | None, full_url: str | None
    ) -> None:
        rtype = resource.get("resourceType")
        rid = resource.get("id")
        if not isinstance(rtype, str) or not isinstance(rid, str):
            return  # a resource without type+id cannot be referenced; skip quietly

        indexed = IndexedResource(
            resource_type=rtype,
            resource_id=rid,
            resource=resource,
            entry_index=entry_index,
            full_url=full_url,
        )

        # Key by (type, id) — id alone is ambiguous across types.
        self._by_type_id[(rtype, rid)] = indexed

        # Index contained resources separately: they live INSIDE this resource,
        # not in the bundle, and are addressed as "#id" from their parent.
        contained = resource.get("contained")
        if isinstance(contained, list):
            for child in cast(list[object], contained):
                if not isinstance(child, dict):
                    continue
                c = cast(dict[str, Any], child)
                ctype = c.get("resourceType")
                cid = c.get("id")
                if isinstance(ctype, str) and isinstance(cid, str):
                    self._contained[(rtype, rid, cid)] = c

        if isinstance(full_url, str):
            lowered = full_url.lower()
            if lowered.startswith(_UUID_PREFIX):
                self._by_uuid[lowered[len(_UUID_PREFIX) :]] = indexed
            elif lowered.startswith(_OID_PREFIX):
                self._by_oid[lowered[len(_OID_PREFIX) :]] = indexed
            else:
                # Absolute URL: parse the last two path segments as Type/id.
                parsed = urlparse(full_url)
                segments = [s for s in parsed.path.split("/") if s]
                if len(segments) >= 2:
                    utype, uid = segments[-2], segments[-1]
                    self._by_type_id.setdefault((utype, uid), indexed)

    # ------------------------------------------------------------------
    # Resolution (pass 2)
    # ------------------------------------------------------------------

    def resolve(
        self, reference: str | None, source_pointer: str = "/", parent: dict[str, Any] | None = None
    ) -> IndexedResource | None:
        """Resolve one reference string. Returns None if unresolvable.

        `parent` is the resource the reference appeared in, needed to resolve
        contained ("#id") references.
        """
        if not isinstance(reference, str):
            return None

        ref = reference.strip()
        if not ref:
            return None

        lowered = ref.lower()

        # 1. Contained reference — "#id", relative to the parent resource.
        if ref.startswith("#"):
            return self._resolve_contained(ref[1:], parent)

        # 2. urn:uuid:
        if lowered.startswith(_UUID_PREFIX):
            return self._by_uuid.get(lowered[len(_UUID_PREFIX) :])

        # 3. urn:oid:
        if lowered.startswith(_OID_PREFIX):
            return self._by_oid.get(lowered[len(_OID_PREFIX) :])

        # 4. Absolute URL — http://host/fhir/Patient/123
        if "://" in ref:
            return self._by_type_id.get(_parse_type_id(ref) or ("", ""))

        # 5. Relative, typed — "Patient/123"
        if "/" in ref:
            key = _parse_type_id(ref)
            return self._by_type_id.get(key) if key else None

        # 6. Bare id — ambiguous; only safe if exactly one resource has it.
        matches = [v for (_, i), v in self._by_type_id.items() if i == ref]
        return matches[0] if len(matches) == 1 else None

    def _resolve_contained(self, cid: str, parent: dict[str, Any] | None) -> IndexedResource | None:
        if not isinstance(parent, dict):
            return None
        ptype = parent.get("resourceType")
        pid = parent.get("id")
        if not isinstance(ptype, str) or not isinstance(pid, str):
            return None
        child = self._contained.get((ptype, pid, cid))
        if child is None:
            return None
        return IndexedResource(
            resource_type=str(child.get("resourceType", "")),
            resource_id=cid,
            resource=child,
            entry_index=None,
            full_url=f"#{cid}",
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    @property
    def report(self) -> ResolutionReport:
        self._report.indexed_count = len(self._by_type_id)
        return self._report

    def record_dangling(self, raw: str, source_pointer: str, reason: str) -> None:
        """Record an unresolvable reference so ENC-001 can fire on it."""
        self._report.dangling.append(
            DanglingReference(raw_reference=raw, source_pointer=source_pointer, reason=reason)
        )

    def __len__(self) -> int:
        return len(self._by_type_id)


def _parse_type_id(ref: str) -> tuple[str, str] | None:
    """Extract (Type, id) from 'Patient/123' or 'http://host/fhir/Patient/123'."""
    parsed = urlparse(ref)
    segments = [s for s in parsed.path.split("/") if s]
    if len(segments) < 2:
        return None
    rtype, rid = segments[-2], segments[-1]
    if not rtype or not rid:
        return None
    return rtype, rid

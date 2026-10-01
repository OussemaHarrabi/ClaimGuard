"""Tenant-scoped collaboration, intake metadata, and operational read models.

Only the RCM-facing methods return claim-linked content. Technical read models
are explicitly projected down to non-PHI metadata and never return drafts.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from typing import Any, TypeVar, cast

from sqlalchemy import text
from sqlalchemy.engine import Engine

from claimguard.edu.envelope import TransportError, validate_transport

_T = TypeVar("_T")


class WorkspaceStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def _rows(self, statement: str, **params: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(text(statement), params).mappings()]

    def _one(self, statement: str, **params: Any) -> dict[str, Any] | None:
        rows = self._rows(statement, **params)
        return rows[0] if rows else None

    def _run_exists(self, tenant_id: str, run_id: str) -> bool:
        return (
            self._one(
                "SELECT 1 FROM claimguard.rule_runs WHERE tenant_id=:tenant AND run_id=:run",
                tenant=tenant_id,
                run=run_id,
            )
            is not None
        )

    def create_request(
        self, tenant_id: str, run_id: str, message: str, actor: str
    ) -> dict[str, Any]:
        if not self._run_exists(tenant_id, run_id):
            raise ValueError("run does not exist in this clinic")
        request_id = uuid.uuid4()
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("""
                INSERT INTO claimguard.clinic_requests
                    (request_id, tenant_id, run_id, message, status, created_by)
                VALUES (:id, :tenant, :run, :message, 'open', :actor)
                RETURNING request_id, run_id, message, response, status, created_by,
                          resolved_by, created_at, resolved_at
            """),
                    {
                        "id": request_id,
                        "tenant": tenant_id,
                        "run": run_id,
                        "message": message,
                        "actor": actor,
                    },
                )
                .mappings()
                .one()
            )
        return dict(row)

    def requests(
        self, tenant_id: str, allowed_claim_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        scope = (
            ""
            if allowed_claim_ids is None
            else """
            AND run_id IN (SELECT run_id FROM claimguard.rule_runs
                           WHERE tenant_id=:tenant AND claim_id = ANY(:claims))
        """
        )
        return self._rows(
            f"""
            SELECT request_id, run_id, message, response, status, created_by,
                   resolved_by, created_at, resolved_at
            FROM claimguard.clinic_requests WHERE tenant_id=:tenant {scope}
            ORDER BY created_at DESC LIMIT 200
        """,  # noqa: S608 - scope is fixed; values remain bound parameters
            tenant=tenant_id,
            claims=allowed_claim_ids,
        )

    def resolve_request(
        self,
        tenant_id: str,
        request_id: str,
        response: str,
        actor: str,
        allowed_claim_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        scope = (
            ""
            if allowed_claim_ids is None
            else """
            AND run_id IN (SELECT run_id FROM claimguard.rule_runs
                           WHERE tenant_id=:tenant AND claim_id = ANY(:claims))
        """
        )
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(f"""
                UPDATE claimguard.clinic_requests
                SET response=:response, status='resolved', resolved_by=:actor, resolved_at=now()
                WHERE tenant_id=:tenant AND request_id=:id AND status='open' {scope}
                RETURNING request_id, run_id, message, response, status, created_by,
                          resolved_by, created_at, resolved_at
            """),  # noqa: S608 - scope is fixed; values remain bound parameters
                    {
                        "tenant": tenant_id,
                        "id": request_id,
                        "response": response,
                        "actor": actor,
                        "claims": allowed_claim_ids,
                    },
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def create_escalation(
        self, tenant_id: str, run_id: str, reason: str, actor: str
    ) -> dict[str, Any]:
        if not self._run_exists(tenant_id, run_id):
            raise ValueError("run does not exist in this clinic")
        escalation_id = uuid.uuid4()
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("""
                INSERT INTO claimguard.clinic_escalations
                    (escalation_id, tenant_id, run_id, reason, status, created_by)
                VALUES (:id, :tenant, :run, :reason, 'open', :actor)
                RETURNING escalation_id, run_id, reason, resolution, status,
                          created_by, resolved_by, created_at, resolved_at
            """),
                    {
                        "id": escalation_id,
                        "tenant": tenant_id,
                        "run": run_id,
                        "reason": reason,
                        "actor": actor,
                    },
                )
                .mappings()
                .one()
            )
        return dict(row)

    def escalations(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT escalation_id, run_id, reason, resolution, status,
                   created_by, resolved_by, created_at, resolved_at
            FROM claimguard.clinic_escalations WHERE tenant_id=:tenant
            ORDER BY created_at DESC LIMIT 200
        """,
            tenant=tenant_id,
        )

    def resolve_escalation(
        self, tenant_id: str, escalation_id: str, resolution: str, actor: str
    ) -> dict[str, Any] | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("""
                UPDATE claimguard.clinic_escalations
                SET resolution=:resolution, status='resolved', resolved_by=:actor, resolved_at=now()
                WHERE tenant_id=:tenant AND escalation_id=:id AND status='open'
                RETURNING escalation_id, run_id, reason, resolution, status,
                          created_by, resolved_by, created_at, resolved_at
            """),
                    {
                        "tenant": tenant_id,
                        "id": escalation_id,
                        "resolution": resolution,
                        "actor": actor,
                    },
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def create_intake_job(
        self,
        tenant_id: str,
        actor: str,
        filename: str,
        content: str,
        source_format: str = "envelope_json",
        files: dict[str, str] | None = None,
        sidecar: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from claimguard.clinic.intake_formats import (
            DetectedFormat,
            IntakeNormalizationError,
            detect_format,
            normalize_csv_package,
            normalize_fhir_with_sidecar,
        )

        has_document = bool(content)
        has_files = files is not None
        if source_format == "auto" and has_document == has_files:
            raise ValueError(
                "auto intake needs either one document or the five CSV files, not both"
            )
        if source_format == "csv_split" and (files is None or content or sidecar is not None):
            raise ValueError("CSV intake needs exactly five files, without JSON content or sidecar")
        if source_format == "fhir_bundle" and (not content or files is not None):
            raise ValueError("FHIR intake needs one Bundle JSON file and no CSV files")
        if source_format == "envelope_json" and (
            not content or files is not None or sidecar is not None
        ):
            raise ValueError("ClaimGuard JSON intake needs one document and no companion files")

        source_content = (
            json.dumps(files, sort_keys=True)
            if source_format == "csv_split" or (source_format == "auto" and has_files)
            else json.dumps({"bundle": content, "sidecar": sidecar}, sort_keys=True)
            if source_format == "fhir_bundle"
            else content
        )
        if len(source_content.encode("utf-8")) > 64 * 1024:
            raise ValueError("document exceeds the 64 KiB pilot limit")
        if source_format == "envelope_json" and not filename.lower().endswith(".json"):
            raise ValueError("the pilot currently accepts ClaimGuard JSON documents only")
        if source_format not in {"envelope_json", "csv_split", "fhir_bundle", "auto"}:
            raise ValueError("unsupported intake source format")
        if not self.configuration(tenant_id)["intake_enabled"]:
            raise ValueError("document intake is disabled for this clinic")
        draft: dict[str, Any] | None = None
        error_code: str | None = None
        try:
            resolved_format: str | None = source_format
            if source_format == "auto":
                # The reviewer did not say which encoding this is; the payload did.
                diagnosis = (
                    detect_format(files)
                    if files is not None
                    else detect_format(content, filenames=(filename,))
                )
                if diagnosis.format is DetectedFormat.UNKNOWN:
                    detail = "; ".join(diagnosis.problems or diagnosis.reasons)
                    error_code = f"unknown_intake_format: {detail}"
                    resolved_format = None
                elif diagnosis.format is DetectedFormat.CSV_PACKAGE and diagnosis.problems:
                    error_code = f"invalid_csv_package: {'; '.join(diagnosis.problems)}"
                    resolved_format = None
                elif diagnosis.format is DetectedFormat.CSV_PACKAGE:
                    resolved_format = "csv_split"
                elif diagnosis.format is DetectedFormat.FHIR_BUNDLE:
                    resolved_format = "fhir_bundle"
                else:
                    resolved_format = "envelope_json"
            if resolved_format == "csv_split":
                draft = normalize_csv_package(files or {})
            elif resolved_format == "fhir_bundle":
                parsed_bundle: object = json.loads(content)
                if not isinstance(parsed_bundle, dict):
                    raise IntakeNormalizationError(
                        "invalid_fhir_package", "Expected a FHIR Bundle JSON object"
                    )
                draft = normalize_fhir_with_sidecar(cast(dict[str, Any], parsed_bundle), sidecar)
            elif resolved_format == "envelope_json":
                parsed: object = json.loads(content)
                envelope = cast(dict[str, object], parsed) if isinstance(parsed, dict) else None
                candidate: object = (
                    envelope.get("claim", envelope) if envelope is not None else None
                )
                if isinstance(candidate, dict):
                    typed_candidate = cast(dict[str, Any], candidate)
                    try:
                        validate_transport(typed_candidate)
                        draft = typed_candidate
                    except TransportError:
                        error_code = "invalid_claim_envelope"
                else:
                    error_code = "invalid_claim_envelope"
        except json.JSONDecodeError:
            error_code = "invalid_json"
        except IntakeNormalizationError as exc:
            error_code = exc.code
        job_id = uuid.uuid4()
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text("""
                INSERT INTO claimguard.intake_jobs
                    (job_id, tenant_id, submitted_by, filename, content_sha256,
                     draft, status, error_code)
                VALUES (:id, :tenant, :actor, :filename, :digest,
                        CAST(:draft AS jsonb), :status, :error)
                RETURNING job_id, filename, content_sha256, status, error_code, created_at
            """),
                    {
                        "id": job_id,
                        "tenant": tenant_id,
                        "actor": actor,
                        "filename": filename,
                        "digest": hashlib.sha256(source_content.encode("utf-8")).hexdigest(),
                        "draft": json.dumps(draft) if draft is not None else None,
                        "status": "needs_review" if draft is not None else "rejected",
                        "error": error_code,
                    },
                )
                .mappings()
                .one()
            )
        return dict(row)

    def intake_jobs(
        self,
        tenant_id: str,
        submitted_by: str | None = None,
        allowed_claim_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        scope = "" if submitted_by is None else " AND submitted_by=:actor"
        claim_scope = (
            ""
            if allowed_claim_ids is None
            else """
            AND (run_id IS NULL OR run_id IN (
                SELECT run_id FROM claimguard.rule_runs
                WHERE tenant_id=:tenant AND claim_id = ANY(:claims)))
        """
        )
        return self._rows(
            f"""
            SELECT job_id, filename, content_sha256, status, error_code, run_id, created_at
            FROM claimguard.intake_jobs WHERE tenant_id=:tenant {scope} {claim_scope}
            ORDER BY created_at DESC LIMIT 200
        """,  # noqa: S608 - scope is fixed; values remain bound parameters
            tenant=tenant_id,
            actor=submitted_by,
            claims=allowed_claim_ids,
        )

    def intake_job(
        self,
        tenant_id: str,
        job_id: str,
        submitted_by: str | None = None,
        allowed_claim_ids: list[str] | None = None,
    ) -> dict[str, Any] | None:
        scope = "" if submitted_by is None else " AND submitted_by=:actor"
        claim_scope = (
            ""
            if allowed_claim_ids is None
            else """
            AND (run_id IS NULL OR run_id IN (
                SELECT run_id FROM claimguard.rule_runs
                WHERE tenant_id=:tenant AND claim_id = ANY(:claims)))
        """
        )
        return self._one(
            f"""
            SELECT job_id, filename, content_sha256, status, error_code, draft, run_id, created_at
            FROM claimguard.intake_jobs
            WHERE tenant_id=:tenant AND job_id=:id {scope} {claim_scope}
        """,  # noqa: S608 - scope is fixed; values remain bound parameters
            tenant=tenant_id,
            id=job_id,
            actor=submitted_by,
            claims=allowed_claim_ids,
        )

    def submit_intake_job(
        self,
        tenant_id: str,
        job_id: str,
        submitted_by: str | None,
        process: Callable[[dict[str, Any]], tuple[str, _T]],
    ) -> _T:
        """Lock one draft through checking and status change; retries cannot race."""
        scope = "" if submitted_by is None else " AND submitted_by=:actor"
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(f"""
                    SELECT draft, status FROM claimguard.intake_jobs
                    WHERE tenant_id=:tenant AND job_id=:id {scope}
                    FOR UPDATE
                """),  # noqa: S608 - scope is fixed; values remain bound parameters
                    {"tenant": tenant_id, "id": job_id, "actor": submitted_by},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise KeyError("intake job not found in this clinic")
            if row["status"] != "needs_review" or not isinstance(row["draft"], dict):
                raise ValueError("intake job is not ready for claim submission")
            run_id, result = process(cast(dict[str, Any], row["draft"]))
            updated = connection.execute(
                text("""
                    UPDATE claimguard.intake_jobs SET status='submitted', run_id=:run
                    WHERE tenant_id=:tenant AND job_id=:id AND status='needs_review'
                """),
                {"tenant": tenant_id, "id": job_id, "run": run_id},
            )
            if updated.rowcount != 1:
                raise RuntimeError("intake job changed during submission")
            return result

    def overview(self, tenant_id: str) -> dict[str, int]:
        return (
            self._one(
                """
            SELECT
              (SELECT count(DISTINCT claim_id) FROM claimguard.rule_runs
               WHERE tenant_id=:tenant) AS claims,
              (SELECT count(*) FROM claimguard.claim_assignments
               WHERE tenant_id=:tenant) AS assigned_claims,
              (SELECT count(*) FROM claimguard.clinic_requests
               WHERE tenant_id=:tenant AND status='open') AS open_requests,
              (SELECT count(*) FROM claimguard.clinic_escalations
               WHERE tenant_id=:tenant AND status='open') AS open_escalations,
              (SELECT count(*) FROM claimguard.intake_jobs
               WHERE tenant_id=:tenant AND status='needs_review') AS intake_pending
        """,
                tenant=tenant_id,
            )
            or {}
        )

    def analytics(self, tenant_id: str) -> dict[str, Any]:
        runs = self._rows(
            """
            SELECT date_trunc('day', created_at)::date AS day, count(*) AS runs,
                   count(DISTINCT claim_id) AS claims
            FROM claimguard.rule_runs WHERE tenant_id=:tenant
            GROUP BY day ORDER BY day DESC LIMIT 30
        """,
            tenant=tenant_id,
        )
        findings = self._rows(
            """
            SELECT status, count(*) AS total FROM claimguard.rule_results
            WHERE tenant_id=:tenant GROUP BY status ORDER BY status
        """,
            tenant=tenant_id,
        )
        return {"daily": runs, "findings_by_status": findings, "overview": self.overview(tenant_id)}

    def review_quality(self, tenant_id: str) -> dict[str, int]:
        return (
            self._one(
                """
            SELECT
              (SELECT count(*) FROM claimguard.review_decisions
               WHERE tenant_id=:tenant) AS decisions,
              (SELECT count(*) FROM claimguard.clinic_escalations
               WHERE tenant_id=:tenant AND status='resolved') AS escalations_resolved,
              (SELECT count(*) FROM claimguard.clinic_escalations
               WHERE tenant_id=:tenant AND status='open') AS escalations_open,
              (SELECT count(*) FROM claimguard.clinic_requests
               WHERE tenant_id=:tenant AND status='resolved') AS requests_resolved
        """,
                tenant=tenant_id,
            )
            or {}
        )

    def activity(
        self, tenant_id: str, allowed_claim_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        scope = "" if allowed_claim_ids is None else " AND r.claim_id = ANY(:claims)"
        return self._rows(
            f"""
            SELECT events.kind, events.run_id, events.actor, events.at FROM (
              SELECT 'claim_checked'::text AS kind, run_id, initiated_by AS actor, created_at AS at
              FROM claimguard.rule_runs WHERE tenant_id=:tenant
              UNION ALL
              SELECT 'review_decision', run_id, actor, created_at
              FROM claimguard.review_decisions WHERE tenant_id=:tenant
              UNION ALL
              SELECT 'request_opened', run_id, created_by, created_at
              FROM claimguard.clinic_requests WHERE tenant_id=:tenant
              UNION ALL
              SELECT 'request_resolved', run_id, resolved_by, resolved_at
              FROM claimguard.clinic_requests WHERE tenant_id=:tenant AND status='resolved'
            ) events JOIN claimguard.rule_runs r ON r.run_id=events.run_id
            WHERE r.tenant_id=:tenant {scope}
            ORDER BY events.at DESC LIMIT 200
        """,  # noqa: S608 - scope is fixed; values remain bound parameters
            tenant=tenant_id,
            claims=allowed_claim_ids,
        )

    def audit(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT r.run_id, r.claim_id, r.version, r.input_hash, r.rule_version,
                   r.model_version, r.prompt_version, r.created_at,
                   e.kind, e.event_id, e.chain_hash
            FROM claimguard.rule_runs r
            JOIN claimguard.audit_events e ON e.claim_ref=r.run_id
            WHERE r.tenant_id=:tenant ORDER BY e.at DESC LIMIT 200
        """,
            tenant=tenant_id,
        )

    def intake_operations(self, tenant_id: str) -> dict[str, Any]:
        counts = self._rows(
            """
            SELECT status, count(*) AS total FROM claimguard.intake_jobs
            WHERE tenant_id=:tenant GROUP BY status ORDER BY status
        """,
            tenant=tenant_id,
        )
        return {"jobs_by_status": counts}

    def versions(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT rule_version, model_version, prompt_version, count(*) AS runs,
                   max(created_at) AS last_used_at
            FROM claimguard.rule_runs WHERE tenant_id=:tenant
            GROUP BY rule_version, model_version, prompt_version
            ORDER BY last_used_at DESC LIMIT 100
        """,
            tenant=tenant_id,
        )

    def redacted_logs(self, tenant_id: str) -> list[dict[str, Any]]:
        return self._rows(
            """
            SELECT job_id, status, error_code, created_at
            FROM claimguard.intake_jobs WHERE tenant_id=:tenant
            ORDER BY created_at DESC LIMIT 200
        """,
            tenant=tenant_id,
        )

    def audit_integrity(self, tenant_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            broken = connection.execute(
                text("SELECT count(*) FROM claimguard.verify_audit_chain()")
            ).scalar_one()
            clinic_events = connection.execute(
                text("""
                    SELECT count(*) FROM claimguard.audit_events e
                    JOIN claimguard.rule_runs r ON r.run_id=e.claim_ref
                    WHERE r.tenant_id=:tenant
                """),
                {"tenant": tenant_id},
            ).scalar_one()
        return {
            "intact": broken == 0,
            "clinic_events_checked": clinic_events,
            "chain_scope": "shared-ledger",
        }

    def configuration(self, tenant_id: str) -> dict[str, bool]:
        row = self._one(
            """
            SELECT intake_enabled FROM claimguard.clinic_configuration WHERE tenant_id=:tenant
        """,
            tenant=tenant_id,
        )
        return {"intake_enabled": bool(row["intake_enabled"]) if row else True}

    def set_configuration(
        self, tenant_id: str, actor: str, intake_enabled: bool
    ) -> dict[str, bool]:
        with self.engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO claimguard.clinic_configuration
                    (tenant_id, intake_enabled, updated_by)
                VALUES (:tenant, :enabled, :actor)
                ON CONFLICT (tenant_id) DO UPDATE
                SET intake_enabled=EXCLUDED.intake_enabled,
                    updated_by=EXCLUDED.updated_by, updated_at=now()
            """),
                {"tenant": tenant_id, "enabled": intake_enabled, "actor": actor},
            )
        return self.configuration(tenant_id)

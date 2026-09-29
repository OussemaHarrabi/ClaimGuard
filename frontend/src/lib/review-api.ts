import type { ReviewWorkspace } from "../components/review-cockpit";

export type ApiEvidence = { path: string; value: unknown };

export type ApiResultRecord = {
  claim_id: string;
  rule_id: string;
  rule_version: string;
  status: string;
  severity: string;
  affected_line_ids: string[];
  evidence: ApiEvidence[];
  rule_source: string;
  explanation: string;
  corrective_action: string;
  confidence: number | null;
  confidence_kind: string;
  requires_human_review: boolean;
  method: string;
  review_status: string;
};

export type ApiReviewState = {
  status: string;
  action: string | null;
  actor: string | null;
  reason: string | null;
  decided_at: string | null;
  decision_count: number;
  unresolved: boolean;
};

export type QueueResponse = {
  filters: {
    status: string | null;
    severity: string | null;
    rule_id: string | null;
    claim_id: string | null;
    include_all: boolean;
  };
  counts: {
    findings: number;
    unresolved: number;
    resolved: number;
    by_rule_status: Record<string, number>;
    by_review_status: Record<string, number>;
    by_severity: Record<string, number>;
  };
  claims: Array<{
    claim_id: string;
    run_id: string;
    version: number;
    findings: number;
    unresolved: number;
    latest_decision_at: string | null;
  }>;
  items: Array<{
    run_id: string;
    claim_id: string;
    version: number;
    run_created_at: string;
    record: ApiResultRecord;
    review: ApiReviewState;
    needs_attention: boolean;
  }>;
};

type ApiRun = {
  run_id: string;
  claim_id: string;
  version: number;
  input_hash: string;
  trace_id: string;
  rule_version: string;
  model_version: string;
  prompt_version: string;
  initiated_by: string;
  created_at: string;
  supersedes_run_id: string | null;
};

export type RunDetailsResponse = {
  run: ApiRun;
  results: ApiResultRecord[];
  explanations: Array<{
    rule_id: string;
    seq: number;
    source: "model" | "deterministic";
    provider: string;
    rewritten: boolean;
    fallback_used: boolean;
    correction_recommendation: string;
    cited_evidence_paths: string[];
    security_decision: "accept" | "fallback" | "decline" | "unrecorded";
    receipt_sha256: string | null;
    rejection_reasons: string[];
    declined_reason: string | null;
    model_assisted: boolean;
  }>;
};

export type DecisionHistoryResponse = {
  run_id: string;
  entries: Array<{
    decision: {
      decision_id: string;
      run_id: string;
      event: {
        claim_id: string;
        rule_id: string;
        action: string;
        actor: string;
        reason: string;
        created_at: string;
        original_status: string;
      };
    };
    review: ApiReviewState;
  }>;
};

export type ClaimEnvelopeResponse = {
  run_id: string;
  claim_id: string;
  version: number;
  claim: Record<string, unknown>;
};

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      detail = payload.detail ?? payload.message ?? detail;
    } catch {
      // The status still gives the reviewer an actionable failure boundary.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export async function getQueue(scope: "mine" | "team" = "mine", signal?: AbortSignal, includeAll = false): Promise<QueueResponse> {
  const path = scope === "mine" ? "/v1/my-queue" : `/v1/queue${includeAll ? "?include_all=true" : ""}`;
  return responseJson<QueueResponse>(await fetch(path, { signal, cache: "no-store" }));
}

export async function getRunDetails(
  runId: string,
  signal?: AbortSignal,
): Promise<RunDetailsResponse> {
  return responseJson<RunDetailsResponse>(
    await fetch(`/v1/runs/${encodeURIComponent(runId)}/results`, { signal, cache: "no-store" }),
  );
}

export async function getDecisionHistory(
  runId: string,
  signal?: AbortSignal,
): Promise<DecisionHistoryResponse> {
  return responseJson<DecisionHistoryResponse>(
    await fetch(`/v1/runs/${encodeURIComponent(runId)}/decisions`, { signal, cache: "no-store" }),
  );
}

export async function getClaimEnvelope(
  runId: string,
  signal?: AbortSignal,
): Promise<ClaimEnvelopeResponse> {
  return responseJson<ClaimEnvelopeResponse>(
    await fetch(`/v1/runs/${encodeURIComponent(runId)}/claim`, { signal, cache: "no-store" }),
  );
}

export async function recordDecision(
  runId: string,
  payload: { ruleId: string; action: string; actor: string; reason: string },
): Promise<void> {
  await responseJson(
    await fetch(`/v1/runs/${encodeURIComponent(runId)}/decisions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        rule_id: payload.ruleId,
        action: payload.action,
        actor: payload.actor,
        reason: payload.reason,
      }),
    }),
  );
}

export async function recheckClaim(
  claimId: string,
  claim: Record<string, unknown>,
  actor: string,
): Promise<{ run: ApiRun }> {
  return responseJson<{ run: ApiRun }>(
    await fetch(`/v1/claims/${encodeURIComponent(claimId)}/recheck`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ claim, actor }),
    }),
  );
}

export function emptyWorkspace(): ReviewWorkspace {
  return {
    counts: { findings: 0, unresolved: 0, resolved: 0 },
    claims: [],
    selected: null,
  };
}

export function buildReviewWorkspace(
  queue: QueueResponse,
  details: RunDetailsResponse | null,
  history: DecisionHistoryResponse | null,
): ReviewWorkspace {
  const reviewByRule = new Map(
    queue.items
      .filter((item) => item.run_id === details?.run.run_id)
      .map((item) => [item.record.rule_id, item.review.status]),
  );
  const historicalReviewByRule = new Map<string, string>();
  for (const entry of history?.entries ?? []) {
    historicalReviewByRule.set(entry.decision.event.rule_id, entry.review.status);
  }
  const provenanceByRule = new Map(
    (details?.explanations ?? []).map((entry) => [entry.rule_id, entry]),
  );

  return {
    counts: {
      findings: queue.counts.findings,
      unresolved: queue.counts.unresolved,
      resolved: queue.counts.resolved,
    },
    claims: queue.claims.map((claim) => ({
      claimId: claim.claim_id,
      runId: claim.run_id,
      version: claim.version,
      findings: claim.findings,
      unresolved: claim.unresolved,
      latestDecisionAt: claim.latest_decision_at,
    })),
    selected: details
      ? {
          run: {
            runId: details.run.run_id,
            claimId: details.run.claim_id,
            version: details.run.version,
            ruleVersion: details.run.rule_version,
            modelVersion: details.run.model_version,
            promptVersion: details.run.prompt_version,
            initiatedBy: details.run.initiated_by,
            createdAt: details.run.created_at,
            supersedesRunId: details.run.supersedes_run_id,
          },
          findings: details.results
            .filter((record) => record.requires_human_review || record.status === "NOT_IMPLEMENTED")
            .map((record) => {
              const provenance = provenanceByRule.get(record.rule_id);
              return {
                ruleId: record.rule_id,
                status: record.status,
                severity: record.severity,
                explanation: record.explanation,
                correctiveAction: record.corrective_action,
                correctionRecommendation:
                  provenance?.correction_recommendation &&
                  !/^No SLM correction recommendation was recorded/i.test(provenance.correction_recommendation)
                    ? provenance.correction_recommendation
                    : record.corrective_action,
                evidence: record.evidence,
                reviewStatus:
                  historicalReviewByRule.get(record.rule_id) ??
                  reviewByRule.get(record.rule_id) ??
                  record.review_status,
                provenance: provenance
                  ? {
                      source: provenance.source,
                      provider: provenance.provider,
                      rewritten: provenance.rewritten,
                      fallbackUsed: provenance.fallback_used,
                      rejectionReasons: provenance.rejection_reasons,
                      declinedReason: provenance.declined_reason,
                      securityDecision: provenance.security_decision,
                      receiptSha256: provenance.receipt_sha256,
                    }
                  : {
                      source: "deterministic" as const,
                      provider: "not-recorded",
                      rewritten: false,
                      fallbackUsed: false,
                      rejectionReasons: [],
                      declinedReason: "No explanation provenance was recorded for this run.",
                      securityDecision: "unrecorded" as const,
                      receiptSha256: null,
                    },
              };
            }),
          decisions: (history?.entries ?? []).map((entry) => ({
            decisionId: entry.decision.decision_id,
            ruleId: entry.decision.event.rule_id,
            action: entry.decision.event.action,
            actor: entry.decision.event.actor,
            reason: entry.decision.event.reason,
            createdAt: entry.decision.event.created_at,
            reviewStatus: entry.review.status,
          })),
        }
      : null,
  };
}

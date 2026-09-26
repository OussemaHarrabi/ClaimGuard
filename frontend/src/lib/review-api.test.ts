import { describe, expect, it } from "vitest";

import { buildReviewWorkspace, type QueueResponse, type RunDetailsResponse, type DecisionHistoryResponse } from "./review-api";

const queue: QueueResponse = {
  filters: { status: null, severity: null, rule_id: null, claim_id: null, include_all: false },
  counts: {
    findings: 1,
    unresolved: 1,
    resolved: 0,
    by_rule_status: { "R003:FAIL": 1 },
    by_review_status: { unreviewed: 1 },
    by_severity: { high: 1 },
  },
  claims: [{ claim_id: "CLM-7", run_id: "RUN-7", version: 2, findings: 1, unresolved: 1, latest_decision_at: null }],
  items: [
    {
      run_id: "RUN-7",
      claim_id: "CLM-7",
      version: 2,
      run_created_at: "2026-09-24T08:35:00Z",
      record: {
        claim_id: "CLM-7",
        rule_id: "R003",
        rule_version: "1.0.0",
        status: "FAIL",
        severity: "high",
        affected_line_ids: [],
        evidence: [{ path: "/coverage/end_date", value: "2026-08-31" }],
        rule_source: "rules/R003@1.0.0",
        explanation: "Coverage ended before service.",
        corrective_action: "Attach current coverage evidence.",
        confidence: null,
        confidence_kind: "not_probabilistic",
        requires_human_review: true,
        method: "deterministic",
        review_status: "unreviewed",
      },
      review: {
        status: "unreviewed",
        action: "request_information",
        actor: "rev-1",
        reason: "Need eligibility proof.",
        decided_at: "2026-09-24T08:40:00Z",
        decision_count: 1,
        unresolved: true,
      },
      needs_attention: true,
    },
  ],
};

const details: RunDetailsResponse = {
  run: {
    run_id: "RUN-7",
    claim_id: "CLM-7",
    version: 2,
    input_hash: "a".repeat(64),
    trace_id: "b".repeat(32),
    rule_version: "1.0.0",
    model_version: "qwen3-4b-benchmark",
    prompt_version: "explain-v1",
    initiated_by: "rev-1",
    created_at: "2026-09-24T08:35:00Z",
    supersedes_run_id: "RUN-6",
  },
  results: [queue.items[0].record],
  explanations: [
    {
      rule_id: "R003",
      seq: 3,
      source: "model",
      provider: "qwen3-4b-benchmark",
      rewritten: true,
      fallback_used: false,
      correction_recommendation: "Verify eligibility evidence, then correct the date or attach proof.",
      cited_evidence_paths: ["/coverage/end_date"],
      security_decision: "accept",
      receipt_sha256: "c".repeat(64),
      rejection_reasons: [],
      declined_reason: null,
      model_assisted: true,
    },
  ],
};

const history: DecisionHistoryResponse = {
  run_id: "RUN-7",
  entries: [
    {
      decision: {
        decision_id: "DEC-1",
        run_id: "RUN-7",
        event: {
          claim_id: "CLM-7",
          rule_id: "R003",
          action: "request_information",
          actor: "rev-1",
          reason: "Need eligibility proof.",
          created_at: "2026-09-24T08:40:00Z",
          original_status: "FAIL",
        },
      },
      review: { ...queue.items[0].review, status: "info_requested" },
    },
  ],
};

describe("buildReviewWorkspace", () => {
  it("maps snake_case API contracts and preserves review state and provenance", () => {
    const workspace = buildReviewWorkspace(queue, details, history);

    expect(workspace.claims[0]).toMatchObject({ claimId: "CLM-7", runId: "RUN-7" });
    expect(workspace.selected?.findings[0]).toMatchObject({
      ruleId: "R003",
      reviewStatus: "info_requested",
      provenance: { source: "model", provider: "qwen3-4b-benchmark" },
    });
    expect(workspace.selected?.decisions[0]).toMatchObject({
      decisionId: "DEC-1",
      reason: "Need eligibility proof.",
    });
  });

  it("uses explicit deterministic provenance when a sidecar entry is unavailable", () => {
    const workspace = buildReviewWorkspace(queue, { ...details, explanations: [] }, history);

    expect(workspace.selected?.findings[0].provenance).toEqual({
      source: "deterministic",
      provider: "not-recorded",
      rewritten: false,
      fallbackUsed: false,
      rejectionReasons: [],
      declinedReason: "No explanation provenance was recorded for this run.",
      securityDecision: "unrecorded",
      receiptSha256: null,
    });
  });
});

import type { ReviewWorkspace } from "../components/review-cockpit";

export const demoWorkspace: ReviewWorkspace = {
  counts: { findings: 7, unresolved: 5, resolved: 2 },
  claims: [
    { claimId: "CLM-240031", runId: "RUN-demo-31", version: 2, findings: 3, unresolved: 2, latestDecisionAt: "2026-09-24T08:40:00Z" },
    { claimId: "CLM-240044", runId: "RUN-demo-44", version: 1, findings: 2, unresolved: 2, latestDecisionAt: null },
    { claimId: "CLM-240051", runId: "RUN-demo-51", version: 3, findings: 2, unresolved: 1, latestDecisionAt: "2026-09-23T15:18:00Z" },
  ],
  selected: {
    run: {
      runId: "RUN-demo-31",
      claimId: "CLM-240031",
      version: 2,
      ruleVersion: "1.0.0",
      modelVersion: "deterministic-engine/1.0.0",
      promptVersion: "none",
      initiatedBy: "reviewer-12",
      createdAt: "2026-09-24T08:35:00Z",
      supersedesRunId: "RUN-demo-30",
    },
    findings: [
      {
        ruleId: "R003",
        status: "FAIL",
        severity: "high",
        explanation: "Coverage ended before the service date.",
        correctiveAction: "Verify eligibility or attach current coverage evidence.",
        correctionRecommendation: "Verify the service date against the eligibility source, then attach current coverage evidence before recheck.",
        evidence: [
          { path: "/coverage/end_date", value: "2026-08-31" },
          { path: "/service_date", value: "2026-09-12" },
        ],
        reviewStatus: "unreviewed",
        provenance: {
          source: "deterministic",
          provider: "template",
          rewritten: true,
          fallbackUsed: false,
          rejectionReasons: [],
          declinedReason: null,
          securityDecision: "accept",
          receiptSha256: "a6f97b453dc503569631ed42fc3970f02d270bb2b8a3f1bd05f3363d6fc88117",
        },
      },
      {
        ruleId: "R007",
        status: "UNABLE_TO_ASSESS",
        severity: "medium",
        explanation: "Authorization evidence is incomplete.",
        correctiveAction: "Request the authorization identifier from the provider.",
        correctionRecommendation: "Request the missing authorization identifier and supporting document before recheck.",
        evidence: [{ path: "/authorizations", value: [] }],
        reviewStatus: "info_requested",
        provenance: {
          source: "deterministic",
          provider: "template",
          rewritten: true,
          fallbackUsed: false,
          rejectionReasons: [],
          declinedReason: null,
          securityDecision: "accept",
          receiptSha256: "00e576f88cf17f4aa4e03085cd2df560755cfda1a533f94329f70b2f4e0e20ad",
        },
      },
    ],
    decisions: [
      {
        decisionId: "DEC-demo-1",
        ruleId: "R007",
        action: "request_information",
        actor: "reviewer-12",
        reason: "Authorization reference is absent.",
        createdAt: "2026-09-24T08:40:00Z",
        reviewStatus: "info_requested",
      },
    ],
  },
};

export const demoClaim: Record<string, unknown> = {
  claim_id: "CLM-240031",
  service_date: "2026-09-12",
  coverage: {
    start_date: "2026-01-01",
    end_date: "2026-08-31",
  },
  authorizations: [],
};

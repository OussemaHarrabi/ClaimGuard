import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ReviewCockpit, type ReviewWorkspace } from "./review-cockpit";

const workspace = {
  counts: { findings: 4, unresolved: 3, resolved: 1 },
  claims: [
    {
      claimId: "CLM-240031",
      runId: "RUN-031",
      version: 2,
      findings: 3,
      unresolved: 2,
      latestDecisionAt: "2026-09-24T08:40:00Z",
    },
    {
      claimId: "CLM-240044",
      runId: "RUN-044",
      version: 1,
      findings: 1,
      unresolved: 1,
      latestDecisionAt: null,
    },
  ],
  selected: {
    run: {
      runId: "RUN-031",
      claimId: "CLM-240031",
      version: 2,
      ruleVersion: "1.0.0",
      modelVersion: "slm-benchmark-pending",
      promptVersion: "explain-v1",
      initiatedBy: "reviewer-12",
      createdAt: "2026-09-24T08:35:00Z",
      supersedesRunId: "RUN-030",
    },
    findings: [
      {
        ruleId: "R004",
        status: "FAIL",
        severity: "high",
        explanation: "Coverage ended before the service date.",
        correctiveAction: "Verify eligibility or attach current coverage evidence.",
        correctionRecommendation: "Verify the service date against the eligibility source, then attach current coverage evidence.",
        evidence: [
          { path: "/coverage/end_date", value: "2026-08-31" },
          { path: "/service_date", value: "2026-09-12" },
        ],
        reviewStatus: "unreviewed",
        provenance: {
          source: "model",
          provider: "benchmark-candidate",
          rewritten: true,
          fallbackUsed: false,
          rejectionReasons: [],
          declinedReason: null,
          securityDecision: "accept",
          receiptSha256: "a".repeat(64),
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
        reviewStatus: "information_requested",
        provenance: {
          source: "deterministic",
          provider: "deterministic-fallback",
          rewritten: false,
          fallbackUsed: true,
          rejectionReasons: ["unsupported citation"],
          declinedReason: "model output rejected by verifier",
          securityDecision: "fallback",
          receiptSha256: "b".repeat(64),
        },
      },
    ],
    decisions: [
      {
        decisionId: "DEC-1",
        ruleId: "R007",
        action: "request_information",
        actor: "reviewer-12",
        reason: "Authorization reference is absent.",
        createdAt: "2026-09-24T08:40:00Z",
        reviewStatus: "information_requested",
      },
    ],
  },
} as const;

function renderCockpit(currentWorkspace: ReviewWorkspace = workspace) {
  const handlers = {
    onSelectClaim: vi.fn(),
    onRefresh: vi.fn(),
    onRecordDecision: vi.fn(),
    onRecheck: vi.fn(),
  };
  render(
    <ReviewCockpit
      workspace={currentWorkspace}
      busy={false}
      error={null}
      reviewer="reviewer-12"
      {...handlers}
    />,
  );
  return handlers;
}

describe("ReviewCockpit", () => {
  it("keeps queue, deterministic findings, and bounded explanation visible together", () => {
    renderCockpit();

    expect(screen.getByRole("heading", { name: "Claims queue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Deterministic findings" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Draft explanation" })).toBeInTheDocument();
    expect(screen.getAllByText("Coverage ended before the service date.")).toHaveLength(2);
    expect(
      within(screen.getByLabelText("Evidence for R004")).getByText("coverage end date"),
    ).toBeInTheDocument();
    expect(screen.getByText(/AI wording cannot change this claim status/i)).toBeInTheDocument();
    expect(screen.getByText("Model-assisted wording")).toBeInTheDocument();
    expect(screen.getByText("benchmark-candidate")).toBeInTheDocument();
    expect(screen.getByText(/Verify the service date against the eligibility source/i)).toBeInTheDocument();
    expect(screen.getByLabelText("SLM correction recommendation for R004")).toBeInTheDocument();
    expect(screen.getByText(/Receipt aaaaaaaa/i)).toBeInTheDocument();
    expect(screen.getAllByText("slm-benchmark-pending")).not.toHaveLength(0);
    expect(screen.getAllByText("explain-v1")).not.toHaveLength(0);
  });

  it("exposes verifier fallback instead of disguising rejected model output", () => {
    renderCockpit();

    const fallback = screen.getByTestId("explanation-R007");
    expect(within(fallback).getByText("Deterministic fallback")).toBeInTheDocument();
    expect(within(fallback).getByLabelText("Safe fallback recommendation for R007")).toBeInTheDocument();
    expect(within(fallback).getByText(/unsupported citation/i)).toBeInTheDocument();
  });

  it("lets the administrator use a verified SLM recommendation as an editable review note", () => {
    renderCockpit();

    fireEvent.click(screen.getByRole("button", { name: "Use R004 recommendation as review note" }));
    expect(screen.getByLabelText("Reviewer note for R004")).toHaveValue(
      "Verify the service date against the eligibility source, then attach current coverage evidence.",
    );
  });

  it("filters the queue by claim id", () => {
    renderCockpit();

    fireEvent.change(screen.getByRole("searchbox", { name: "Search claims" }), {
      target: { value: "240044" },
    });

    expect(screen.getByRole("button", { name: /Open claim CLM-240044/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Open claim CLM-240031/i })).not.toBeInTheDocument();
  });

  it("offers all four bounded review actions with a mandatory note", () => {
    renderCockpit();
    const note = screen.getByLabelText("Reviewer note for R004");

    expect(within(note.closest("article")!).getByRole("button", { name: "Dismiss with reason" })).toBeDisabled();
    expect(within(note.closest("article")!).getByRole("button", { name: "Mark corrected for recheck" })).toBeDisabled();
    fireEvent.change(note, { target: { value: "Verified against the source." } });
    expect(within(note.closest("article")!).getByRole("button", { name: "Dismiss with reason" })).toBeEnabled();
    expect(within(note.closest("article")!).getByRole("button", { name: "Mark corrected for recheck" })).toBeEnabled();
  });

  it("matches the backend transition table for decided and superseded findings", () => {
    const transitioned: ReviewWorkspace = {
      ...workspace,
      selected: workspace.selected
        ? {
            ...workspace.selected,
            findings: [
              { ...workspace.selected.findings[0], reviewStatus: "confirmed" },
              { ...workspace.selected.findings[1], reviewStatus: "corrected_for_recheck" },
            ],
          }
        : null,
    };
    renderCockpit(transitioned);

    const confirmedNote = screen.getByLabelText("Reviewer note for R004");
    fireEvent.change(confirmedNote, { target: { value: "New evidence arrived." } });
    const confirmedFinding = within(confirmedNote.closest("article")!);
    expect(confirmedFinding.getByRole("button", { name: "Request information" })).toBeEnabled();
    expect(confirmedFinding.getByRole("button", { name: "Mark corrected for recheck" })).toBeEnabled();
    expect(confirmedFinding.getByRole("button", { name: "Confirm issue" })).toBeDisabled();
    expect(confirmedFinding.getByRole("button", { name: "Dismiss with reason" })).toBeDisabled();

    const supersededNote = screen.getByLabelText("Reviewer note for R007");
    fireEvent.change(supersededNote, { target: { value: "This old run is superseded." } });
    const supersededFinding = within(supersededNote.closest("article")!);
    for (const action of [
      "Request information",
      "Confirm issue",
      "Dismiss with reason",
      "Mark corrected for recheck",
    ]) {
      expect(supersededFinding.getByRole("button", { name: action })).toBeDisabled();
    }
  });

  it("derives a completed header from the claim review state", () => {
    const resolved: ReviewWorkspace = {
      ...workspace,
      claims: workspace.claims.map((claim) =>
        claim.runId === "RUN-031" ? { ...claim, unresolved: 0 } : claim,
      ),
      selected: workspace.selected
        ? {
            ...workspace.selected,
            findings: workspace.selected.findings.map((finding) => ({
              ...finding,
              reviewStatus: "confirmed",
            })),
          }
        : null,
    };
    renderCockpit(resolved);

    expect(screen.getByText("Review complete")).toBeInTheDocument();
    expect(screen.queryByText("Needs review")).not.toBeInTheDocument();
  });

  it("routes queue selection, reasoned decisions, and recheck through explicit callbacks", () => {
    const handlers = renderCockpit();

    fireEvent.click(screen.getByRole("button", { name: /Open claim CLM-240044/i }));
    expect(handlers.onSelectClaim).toHaveBeenCalledWith("RUN-044", "CLM-240044");

    const r004Note = screen.getByLabelText("Reviewer note for R004");
    fireEvent.change(r004Note, {
      target: { value: "Confirmed against the eligibility source." },
    });
    fireEvent.click(within(r004Note.closest("article")!).getByRole("button", { name: "Confirm issue" }));
    expect(handlers.onRecordDecision).toHaveBeenCalledWith(
      "R004",
      "confirm_issue",
      "Confirmed against the eligibility source.",
    );

    fireEvent.click(screen.getByRole("button", { name: "Recheck claim" }));
    expect(handlers.onRecheck).toHaveBeenCalledWith("CLM-240031");
  });
});

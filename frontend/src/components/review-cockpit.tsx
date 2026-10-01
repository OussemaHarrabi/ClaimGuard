"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Check,
  CircleAlert,
  FileCheck2,
  History,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import { Button } from "./ui/button";
import { Badge } from "./ui/badge";
import { Input } from "./ui/input";
import { Textarea } from "./ui/textarea";
import { fieldLabel, plainIssue, plainRecommendation } from "../lib/claim-editor";

export type Evidence = {
  readonly path: string;
  readonly value: unknown;
};

export type Provenance = {
  readonly source: "model" | "deterministic";
  readonly provider: string;
  readonly rewritten: boolean;
  readonly fallbackUsed: boolean;
  readonly rejectionReasons: readonly string[];
  readonly declinedReason: string | null;
  readonly securityDecision: "accept" | "fallback" | "decline" | "unrecorded";
  readonly receiptSha256: string | null;
};

export type Finding = {
  readonly ruleId: string;
  readonly status: string;
  readonly severity: string;
  readonly explanation: string;
  readonly correctiveAction: string;
  readonly correctionRecommendation: string;
  readonly evidence: readonly Evidence[];
  readonly reviewStatus: string;
  readonly provenance: Provenance;
};

export type ClaimSummary = {
  readonly claimId: string;
  readonly runId: string;
  readonly version: number;
  readonly findings: number;
  readonly unresolved: number;
  readonly latestDecisionAt: string | null;
};

export type Decision = {
  readonly decisionId: string;
  readonly ruleId: string;
  readonly action: string;
  readonly actor: string;
  readonly reason: string;
  readonly createdAt: string;
  readonly reviewStatus: string;
};

export type Run = {
  readonly runId: string;
  readonly claimId: string;
  readonly version: number;
  readonly ruleVersion: string;
  readonly modelVersion: string;
  readonly promptVersion: string;
  readonly initiatedBy: string;
  readonly createdAt: string;
  readonly supersedesRunId: string | null;
};

export type ReviewWorkspace = {
  readonly counts: {
    readonly findings: number;
    readonly unresolved: number;
    readonly resolved: number;
  };
  readonly claims: readonly ClaimSummary[];
  readonly selected: {
    readonly run: Run;
    readonly findings: readonly Finding[];
    readonly decisions: readonly Decision[];
    readonly totalChecks?: number;
    readonly outcomes?: readonly { ruleId: string; status: string }[];
  } | null;
};

type ReviewAction =
  | "request_information"
  | "confirm_issue"
  | "dismiss_with_reason"
  | "mark_corrected_for_recheck";

const ALL_REVIEW_ACTIONS: readonly ReviewAction[] = [
  "request_information",
  "confirm_issue",
  "dismiss_with_reason",
  "mark_corrected_for_recheck",
];

const RULE_TITLES: Record<string, string> = {
  R001: "Required claim information", R002: "Service and submission chronology",
  R003: "Coverage active on service date", R004: "Member and beneficiary consistency",
  R005: "Provider in the supplied network", R006: "Possible duplicate service lines",
  R007: "Line arithmetic", R008: "Required authorization reference",
  R009: "Authorization record matches service", R010: "Required supporting document",
  R011: "Service code in fictional catalogue", R012: "Claim total equals line amounts",
  R013: "Quantity and price limits", R014: "Submission window",
  R015: "Currency matches policy",
};

function reviewerExplanation(finding: Finding): string {
  return `Issue: ${plainIssue(finding.explanation)}`;
}

const ALLOWED_ACTIONS_BY_STATUS: Readonly<Record<string, readonly ReviewAction[]>> = {
  unreviewed: ALL_REVIEW_ACTIONS,
  info_requested: ALL_REVIEW_ACTIONS,
  information_requested: ALL_REVIEW_ACTIONS,
  confirmed: ["request_information", "mark_corrected_for_recheck"],
  dismissed: ["request_information", "mark_corrected_for_recheck"],
  corrected_for_recheck: [],
};

type ReviewCockpitProps = {
  readonly queueTitle?: string;
  readonly workspace: ReviewWorkspace;
  readonly busy: boolean;
  readonly error: string | null;
  readonly reviewer: string;
  readonly onSelectClaim: (runId: string, claimId: string) => void;
  readonly onRefresh: () => void;
  readonly onRecordDecision: (ruleId: string, action: ReviewAction, reason: string) => void;
  readonly onRecheck: (claimId: string) => void;
};

function titleCase(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function evidenceLabel(path: string) {
  try { return fieldLabel(path); }
  catch { return path.replace(/^\//, "").replaceAll("/", " ").replaceAll("_", " ") || "claim evidence"; }
}

function evidenceValue(value: unknown) {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function relativeActivity(value: string | null) {
  if (!value) return "Awaiting review";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function statusTone(status: string) {
  if (status === "FAIL") return "danger";
  if (status === "UNABLE_TO_ASSESS") return "warning";
  if (status === "PASS") return "success";
  return "neutral";
}

function decisionDisabled(
  finding: Finding,
  action: ReviewAction,
  note: string,
  busy: boolean,
) {
  const allowed = ALLOWED_ACTIONS_BY_STATUS[finding.reviewStatus] ?? [];
  return !note.trim() || busy || !allowed.includes(action);
}

function FindingGuidance({ finding, run }: { finding: Finding; run: Run }) {
  const verifierDetail = [
    ...finding.provenance.rejectionReasons,
    finding.provenance.declinedReason,
  ].filter((reason): reason is string => Boolean(reason));
  const recommendationKind = finding.provenance.fallbackUsed
    ? "Safe fallback recommendation"
    : finding.provenance.source === "model"
      ? "SLM correction recommendation"
      : "Rule-based next step";
  return <aside className="explanation-block" data-testid={`explanation-${finding.ruleId}`} aria-label={`Explanation and next step for ${finding.ruleId}`}>
    <div className="provenance-line">
      <span className={`provenance ${finding.provenance.fallbackUsed ? "fallback" : "assisted"}`}>
        {finding.provenance.fallbackUsed ? "Deterministic fallback" : finding.provenance.source === "model" ? "Model-assisted wording" : "Deterministic wording"}
      </span>
      <span>{finding.ruleId}</span>
    </div>
    <p>{reviewerExplanation(finding)}</p>
    <section className="correction-recommendation" aria-label={`${recommendationKind} for ${finding.ruleId}`}>
      <span>{recommendationKind}</span>
      <p>{plainRecommendation(finding.correctionRecommendation)}</p>
      <small>Verify against source documents. No claim field is changed automatically.</small>
    </section>
    <details className="technical-provenance"><summary>Technical provenance for {finding.ruleId}</summary>
      <dl className="provenance-details" aria-label={`Provenance for ${finding.ruleId}`}>
        <div><dt>Provider</dt><dd>{finding.provenance.provider}</dd></div>
        <div><dt>Run model</dt><dd>{run.modelVersion}</dd></div>
        <div><dt>Prompt</dt><dd>{run.promptVersion}</dd></div>
        <div><dt>Wording</dt><dd>{finding.provenance.rewritten ? "Rewritten" : "Engine original"}</dd></div>
        <div><dt>Security</dt><dd>{titleCase(finding.provenance.securityDecision)}</dd></div>
        <div><dt>Receipt</dt><dd title={finding.provenance.receiptSha256 ?? "Not recorded"}>{finding.provenance.receiptSha256 ? `Receipt ${finding.provenance.receiptSha256.slice(0, 8)}` : "Not recorded"}</dd></div>
      </dl>
    </details>
    <div className="citation-row">{finding.evidence.map((entry, index) => <span className="citation" key={entry.path}>E{index + 1} · {evidenceLabel(entry.path)}</span>)}</div>
    {verifierDetail.length ? <div className="verifier-warning"><AlertTriangle size={16} aria-hidden="true" /><span>Draft guidance not used: {verifierDetail.join(", ")}.</span></div> : null}
  </aside>;
}

export function ReviewCockpit({
  queueTitle = "Claims queue",
  workspace,
  busy,
  error,
  onSelectClaim,
  onRefresh,
  onRecordDecision,
  onRecheck,
}: ReviewCockpitProps) {
  const selected = workspace.selected;
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [claimQuery, setClaimQuery] = useState("");
  const [queueFilter, setQueueFilter] = useState("all");
  const visibleClaims = workspace.claims.filter((claim) =>
    claim.claimId.toLocaleLowerCase().includes(claimQuery.trim().toLocaleLowerCase()) &&
    (queueFilter === "all" || (queueFilter === "open" ? claim.unresolved > 0 : claim.unresolved === 0)),
  );
  const selectedClaim = workspace.claims.find((claim) => claim.runId === selected?.run.runId);
  const selectedUnresolved =
    selectedClaim?.unresolved ??
    selected?.findings.filter((finding) =>
      ["unreviewed", "info_requested", "information_requested"].includes(finding.reviewStatus),
    ).length ??
    0;

  return (
    <div className="app-shell">
      <a className="skip-link" href="#review-main">
        Skip to review workspace
      </a>

      {error ? (
        <div className="global-error" role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <span>{error}</span>
          <button type="button" onClick={onRefresh}>
            Try again
          </button>
        </div>
      ) : null}

      <main className="review-grid" id="review-main" aria-busy={busy}>
        <section className="queue-panel" id="queue" aria-labelledby="queue-title">
          <div className="panel-heading queue-heading">
            <div>
              <p className="eyebrow">Review workspace</p>
              <h1 id="queue-title">{queueTitle}</h1>
            </div>
            <Button
              className="icon-button"
              variant="outline"
              size="icon"
              type="button"
              aria-label="Refresh claims queue"
              onClick={onRefresh}
              disabled={busy}
            >
              <RefreshCw size={18} aria-hidden="true" />
            </Button>
          </div>

          <label className="search-field">
            <span>Search claims</span>
            <span className="search-control">
              <Search size={17} aria-hidden="true" />
              <Input
                type="search"
                placeholder="Claim ID"
                value={claimQuery}
                onChange={(event) => setClaimQuery(event.target.value)}
              />
            </span>
          </label>

          <div className="queue-filters" aria-label="Filter claims by review state">{[["all", "All"], ["open", "Needs review"], ["complete", "Reviewed"]].map(([value, label]) => <button type="button" key={value} aria-pressed={queueFilter === value} onClick={() => setQueueFilter(value)}>{label}</button>)}</div>

          <div className="queue-summary" aria-label="Queue summary">
            <span>
              <strong>{workspace.counts.unresolved}</strong> unresolved
            </span>
            <span>
              <strong>{workspace.counts.resolved}</strong> resolved
            </span>
            <span>
              <strong>{workspace.counts.findings}</strong> findings
            </span>
          </div>

          <div className="claim-list" role="list" aria-label="Claims needing attention">
            {visibleClaims.map((claim) => {
              const active = selected?.run.runId === claim.runId;
              return (
                <button
                  className={`claim-row${active ? " selected" : ""}`}
                  type="button"
                  key={claim.runId}
                  aria-label={`Open claim ${claim.claimId}, ${claim.unresolved} unresolved findings`}
                  aria-current={active ? "true" : undefined}
                  onClick={() => onSelectClaim(claim.runId, claim.claimId)}
                >
                  <span className="claim-selector" aria-hidden="true">
                    {active ? <Check size={13} /> : null}
                  </span>
                  <span className="claim-row-main">
                    <strong>{claim.claimId}</strong>
                    <span>Version {claim.version}</span>
                  </span>
                  <span className="claim-row-meta">
                    <span className={`queue-status${claim.unresolved ? " needs-work" : " resolved"}`}>
                      {claim.unresolved ? `${claim.unresolved} unresolved` : "Resolved"}
                    </span>
                    <span>{relativeActivity(claim.latestDecisionAt)}</span>
                  </span>
                </button>
              );
            })}
            {!visibleClaims.length ? (
              <p className="queue-empty">{busy ? "Loading your claims…" : !workspace.claims.length ? "Your queue is clear. Assigned claims will appear here when they are ready for review." : "No claims match these filters. Try another claim ID or choose All."}</p>
            ) : null}
          </div>
        </section>

        <section className="findings-panel" id="findings" aria-labelledby="findings-title">
          {selected ? (
            <>
              <header className="claim-header">
                <div>
                  <p className="eyebrow">Selected claim</p>
                  <div className="claim-title-line">
                    <h2>{selected.run.claimId}</h2>
                    <Badge className={`status-chip ${selectedUnresolved ? "danger" : "success"}`} variant={selectedUnresolved ? "destructive" : "secondary"}>
                      {selectedUnresolved ? "Needs review" : "Review complete"}
                    </Badge>
                  </div>
                </div>
                <dl className="run-facts">
                  <div>
                    <dt>Run</dt>
                    <dd>{selected.run.runId}</dd>
                  </div>
                  <div>
                    <dt>Version</dt>
                    <dd>{selected.run.version}</dd>
                  </div>
                  <div>
                    <dt>Rule set</dt>
                    <dd>{selected.run.ruleVersion}</dd>
                  </div>
                </dl>
              </header>

              {selectedUnresolved ? (
                <section className="review-resolution" aria-labelledby="review-resolution-title">
                  <div>
                    <p className="eyebrow">Next action</p>
                    <h3 id="review-resolution-title">Resolve this claim</h3>
                    <p>Compare the flagged values with the source documents. If a value is wrong, correct only what the documents support. Then create a new version to rerun the checks.</p>
                    <p>If evidence is missing, add a reviewer note below and request information instead.</p>
                  </div>
                  <Button className="primary-button" type="button" disabled={busy} onClick={() => onRecheck(selected.run.claimId)}>
                    <RefreshCw size={17} aria-hidden="true" />
                    Correct claim &amp; recheck
                  </Button>
                </section>
              ) : null}

              <div className="section-heading paired-review-heading">
                <div>
                  <p className="eyebrow">Check the source values</p>
                  <h2 id="findings-title">Deterministic findings</h2>
                </div>
                <div><p className="eyebrow">Human-readable guidance</p><h2 id="explanation-title">Explanation &amp; next step</h2></div>
                <span className="finding-count">{selected.totalChecks ?? selected.findings.length} rules run · {selected.findings.length} need review</span>
              </div>
              <p className="status-boundary"><ShieldCheck size={17} aria-hidden="true" />AI wording cannot change this claim status. The deterministic engine remains authoritative.</p>

              {selected.outcomes ? <details className="all-rule-outcomes"><summary>View all {selected.outcomes.length} rule outcomes</summary><ol>{selected.outcomes.map((outcome) => <li key={outcome.ruleId}><span>{outcome.ruleId}</span><strong>{titleCase(outcome.status)}</strong></li>)}</ol></details> : null}

              <div className="finding-stack">
                {selected.findings.map((finding, index) => (
                  <article className="finding-row" data-testid={`finding-${finding.ruleId}`} key={finding.ruleId}>
                    <div className={`finding-index ${statusTone(finding.status)}`} aria-hidden="true">
                      {index + 1}
                    </div>
                    <div className="finding-content">
                      <div className="finding-title">
                        <div>
                          <span className="rule-id">{finding.ruleId}</span>
                          <h3>{RULE_TITLES[finding.ruleId] ?? `Check ${finding.ruleId}`}</h3>
                        </div>
                        <Badge className={`status-chip ${statusTone(finding.status)}`} variant={finding.status === "FAIL" ? "destructive" : "secondary"}>
                          {titleCase(finding.severity)} · {titleCase(finding.status)}
                        </Badge>
                      </div>
                      <div className="evidence-list" aria-label={`Evidence for ${finding.ruleId}`}>
                        {finding.evidence.map((entry) => (
                          <span
                            className="evidence-item"
                            key={entry.path}
                          >
                            <span>{evidenceLabel(entry.path)}</span>
                            <strong>{evidenceValue(entry.value)}</strong>
                          </span>
                        ))}
                      </div>
                      <div className="finding-actions">
                        <label className="review-note">
                          <span>Reviewer note for {finding.ruleId}</span>
                          <Textarea
                            rows={2}
                            value={reviewNotes[finding.ruleId] ?? ""}
                            placeholder="Record the evidence behind your decision"
                            onChange={(event) =>
                              setReviewNotes((notes) => ({
                                ...notes,
                                [finding.ruleId]: event.target.value,
                              }))
                            }
                          />
                        </label>
                        <p className="review-decision-help">These decisions record your review; they do not change claim fields.</p>
                        <Button
                          className="text-button"
                          variant="outline"
                          type="button"
                          disabled={decisionDisabled(
                            finding,
                            "request_information",
                            reviewNotes[finding.ruleId] ?? "",
                            busy,
                          )}
                          onClick={() =>
                            onRecordDecision(
                              finding.ruleId,
                              "request_information",
                              reviewNotes[finding.ruleId],
                            )
                          }
                        >
                          Request information
                        </Button>
                        <Button
                          className="text-button"
                          variant="outline"
                          type="button"
                          disabled={decisionDisabled(
                            finding,
                            "confirm_issue",
                            reviewNotes[finding.ruleId] ?? "",
                            busy,
                          )}
                          onClick={() =>
                            onRecordDecision(
                              finding.ruleId,
                              "confirm_issue",
                              reviewNotes[finding.ruleId],
                            )
                          }
                        >
                          Confirm issue
                        </Button>
                        <Button
                          className="text-button"
                          variant="outline"
                          type="button"
                          disabled={decisionDisabled(
                            finding,
                            "dismiss_with_reason",
                            reviewNotes[finding.ruleId] ?? "",
                            busy,
                          )}
                          onClick={() =>
                            onRecordDecision(
                              finding.ruleId,
                              "dismiss_with_reason",
                              reviewNotes[finding.ruleId],
                            )
                          }
                        >
                          Dismiss with reason
                        </Button>
                        <Button
                          className="text-button"
                          variant="outline"
                          type="button"
                          disabled={decisionDisabled(
                            finding,
                            "mark_corrected_for_recheck",
                            reviewNotes[finding.ruleId] ?? "",
                            busy,
                          )}
                          onClick={() =>
                            onRecordDecision(
                              finding.ruleId,
                              "mark_corrected_for_recheck",
                              reviewNotes[finding.ruleId],
                            )
                          }
                        >
                          Mark corrected for recheck
                        </Button>
                        <span>{titleCase(finding.reviewStatus)}</span>
                      </div>
                    </div>
                    <FindingGuidance finding={finding} run={selected.run} />
                  </article>
                ))}
              </div>

              <section className="audit-preview" id="audit" aria-labelledby="audit-title">
                <div className="audit-heading"><h3 id="audit-title">Recent audit activity</h3><History size={16} aria-hidden="true" /></div>
                {selected.decisions.length ? <ol>{selected.decisions.slice(-3).map((decision) => <li key={decision.decisionId}><span>{decision.actor}</span><strong>{titleCase(decision.action)}</strong><time dateTime={decision.createdAt}>{relativeActivity(decision.createdAt)}</time></li>)}</ol> : <p>No reviewer decisions recorded for this version.</p>}
              </section>

            </>
          ) : (
            <div className="empty-state">
              <FileCheck2 size={28} aria-hidden="true" />
              <h2 id="findings-title">Select a claim to review</h2>
              <p>Choose a queue item to inspect its deterministic checks and evidence.</p>
            </div>
          )}
        </section>

      </main>
    </div>
  );
}

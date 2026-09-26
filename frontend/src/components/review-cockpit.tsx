"use client";

import { useState } from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  CircleAlert,
  FileCheck2,
  History,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

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

const ALLOWED_ACTIONS_BY_STATUS: Readonly<Record<string, readonly ReviewAction[]>> = {
  unreviewed: ALL_REVIEW_ACTIONS,
  info_requested: ALL_REVIEW_ACTIONS,
  information_requested: ALL_REVIEW_ACTIONS,
  confirmed: ["request_information", "mark_corrected_for_recheck"],
  dismissed: ["request_information", "mark_corrected_for_recheck"],
  corrected_for_recheck: [],
};

type ReviewCockpitProps = {
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
  const readable = path.replace(/^\//, "").replaceAll("/", " ").replaceAll("_", " ");
  return readable || "claim evidence";
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

export function ReviewCockpit({
  workspace,
  busy,
  error,
  reviewer,
  onSelectClaim,
  onRefresh,
  onRecordDecision,
  onRecheck,
}: ReviewCockpitProps) {
  const selected = workspace.selected;
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [claimQuery, setClaimQuery] = useState("");
  const visibleClaims = workspace.claims.filter((claim) =>
    claim.claimId.toLocaleLowerCase().includes(claimQuery.trim().toLocaleLowerCase()),
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

      <header className="topbar">
        <a className="brand" href="#review-main" aria-label="ClaimGuard review workspace">
          <span className="brand-mark" aria-hidden="true">
            <ShieldCheck size={21} strokeWidth={2.2} />
          </span>
          <span>ClaimGuard</span>
        </a>

        <nav className="primary-nav" aria-label="Primary navigation">
          <a className="nav-link active" href="#queue" aria-current="page">
            Queue
          </a>
          <a className="nav-link" href="#findings">
            Review
          </a>
          <a className="nav-link" href="#audit">
            Audit
          </a>
        </nav>

        <div className="reviewer">
          <span className="avatar" aria-hidden="true">
            {reviewer.slice(0, 2).toUpperCase()}
          </span>
          <span className="reviewer-copy">
            <strong>{reviewer}</strong>
            <span>Claims reviewer</span>
          </span>
          <ChevronDown size={16} aria-hidden="true" />
        </div>
      </header>

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
              <h1 id="queue-title">Claims queue</h1>
            </div>
            <button
              className="icon-button"
              type="button"
              aria-label="Refresh claims queue"
              onClick={onRefresh}
              disabled={busy}
            >
              <RefreshCw size={18} aria-hidden="true" />
            </button>
          </div>

          <label className="search-field">
            <span>Search claims</span>
            <span className="search-control">
              <Search size={17} aria-hidden="true" />
              <input
                type="search"
                placeholder="Claim ID"
                value={claimQuery}
                onChange={(event) => setClaimQuery(event.target.value)}
              />
            </span>
          </label>

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
              <p className="queue-empty">No claim IDs match “{claimQuery.trim()}”.</p>
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
                    <span className={`status-chip ${selectedUnresolved ? "danger" : "success"}`}>
                      {selectedUnresolved ? "Needs review" : "Review complete"}
                    </span>
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

              <div className="section-heading">
                <div>
                  <p className="eyebrow">Engine output</p>
                  <h2 id="findings-title">Deterministic findings</h2>
                </div>
                <span className="finding-count">{selected.findings.length} checks</span>
              </div>

              <div className="finding-stack">
                {selected.findings.map((finding, index) => (
                  <article className="finding-row" key={finding.ruleId}>
                    <div className={`finding-index ${statusTone(finding.status)}`} aria-hidden="true">
                      {index + 1}
                    </div>
                    <div className="finding-content">
                      <div className="finding-title">
                        <div>
                          <span className="rule-id">{finding.ruleId}</span>
                          <h3>{finding.explanation}</h3>
                        </div>
                        <span className={`status-chip ${statusTone(finding.status)}`}>
                          {titleCase(finding.severity)} · {titleCase(finding.status)}
                        </span>
                      </div>
                      <p className="corrective-action">{finding.correctiveAction}</p>
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
                          <textarea
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
                        <button
                          className="text-button"
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
                        </button>
                        <button
                          className="text-button"
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
                        </button>
                        <button
                          className="text-button"
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
                        </button>
                        <button
                          className="text-button"
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
                        </button>
                        <span>{titleCase(finding.reviewStatus)}</span>
                      </div>
                    </div>
                  </article>
                ))}
              </div>

              <footer className="findings-actions-bar">
                <button
                  className="primary-button"
                  type="button"
                  onClick={() => onRecheck(selected.run.claimId)}
                >
                  <RefreshCw size={17} aria-hidden="true" />
                  Recheck claim
                </button>
              </footer>
            </>
          ) : (
            <div className="empty-state">
              <FileCheck2 size={28} aria-hidden="true" />
              <h2 id="findings-title">Select a claim to review</h2>
              <p>Choose a queue item to inspect its deterministic checks and evidence.</p>
            </div>
          )}
        </section>

        <aside className="explanation-panel" aria-labelledby="explanation-title">
          <div className="section-heading explanation-heading">
            <div>
              <p className="eyebrow">Bounded AI assistance</p>
              <h2 id="explanation-title">Draft explanation</h2>
            </div>
            <span className="ai-mark" aria-hidden="true">
              <Sparkles size={17} />
            </span>
          </div>

          {selected ? (
            <>
              <p className="status-boundary">
                <ShieldCheck size={17} aria-hidden="true" />
                AI wording cannot change this claim status. The deterministic engine remains authoritative.
              </p>

              <div className="explanation-list">
                {selected.findings.map((finding) => {
                  const verifierDetail = [
                    ...finding.provenance.rejectionReasons,
                    finding.provenance.declinedReason,
                  ].filter((reason): reason is string => Boolean(reason));
                  const recommendationKind = finding.provenance.fallbackUsed
                    ? "Safe fallback recommendation"
                    : finding.provenance.source === "model"
                      ? "SLM correction recommendation"
                      : "Deterministic recommendation";
                  return (
                    <article
                    className="explanation-block"
                    data-testid={`explanation-${finding.ruleId}`}
                    key={finding.ruleId}
                  >
                    <div className="provenance-line">
                      <span className={`provenance ${finding.provenance.fallbackUsed ? "fallback" : "assisted"}`}>
                        {finding.provenance.fallbackUsed
                          ? "Deterministic fallback"
                          : finding.provenance.source === "model"
                            ? "Model-assisted wording"
                            : "Deterministic wording"}
                      </span>
                      <span>{finding.ruleId}</span>
                    </div>
                    <p>{finding.explanation}</p>
                    <section
                      className="correction-recommendation"
                      aria-label={`${recommendationKind} for ${finding.ruleId}`}
                    >
                      <span>{recommendationKind}</span>
                      <p>{finding.correctionRecommendation}</p>
                      <small>Human review required · no claim field is changed automatically.</small>
                      <button
                        aria-label={`Use ${finding.ruleId} recommendation as review note`}
                        className="recommendation-button"
                        onClick={() =>
                          setReviewNotes((current) => ({
                            ...current,
                            [finding.ruleId]: finding.correctionRecommendation,
                          }))
                        }
                        type="button"
                      >
                        Use as editable note
                      </button>
                    </section>
                    <dl className="provenance-details" aria-label={`Provenance for ${finding.ruleId}`}>
                      <div>
                        <dt>Provider</dt>
                        <dd>{finding.provenance.provider}</dd>
                      </div>
                      <div>
                        <dt>Run model</dt>
                        <dd>{selected.run.modelVersion}</dd>
                      </div>
                      <div>
                        <dt>Prompt</dt>
                        <dd>{selected.run.promptVersion}</dd>
                      </div>
                      <div>
                        <dt>Wording</dt>
                        <dd>{finding.provenance.rewritten ? "Rewritten" : "Engine original"}</dd>
                      </div>
                      <div>
                        <dt>Security</dt>
                        <dd>{titleCase(finding.provenance.securityDecision)}</dd>
                      </div>
                      <div>
                        <dt>Receipt</dt>
                        <dd title={finding.provenance.receiptSha256 ?? "Not recorded"}>
                          {finding.provenance.receiptSha256
                            ? `Receipt ${finding.provenance.receiptSha256.slice(0, 8)}`
                            : "Not recorded"}
                        </dd>
                      </div>
                    </dl>
                    <div className="citation-row">
                      {finding.evidence.map((entry, index) => (
                        <span className="citation" key={entry.path}>
                          E{index + 1} · {evidenceLabel(entry.path)}
                        </span>
                      ))}
                    </div>
                    {verifierDetail.length ? (
                      <div className="verifier-warning">
                        <AlertTriangle size={16} aria-hidden="true" />
                        <span>Model draft rejected: {verifierDetail.join(", ")}.</span>
                      </div>
                    ) : null}
                  </article>
                  );
                })}
              </div>

              <section className="suggestion" aria-labelledby="suggestion-title">
                <div className="suggestion-title">
                  <span className="suggestion-icon" aria-hidden="true">
                    <FileCheck2 size={17} />
                  </span>
                  <div>
                    <p className="eyebrow">Human approval required</p>
                    <h3 id="suggestion-title">Suggested correction</h3>
                  </div>
                </div>
                <p>{selected.findings[0]?.correctiveAction ?? "No correction proposed."}</p>
                <button
                  className="secondary-button full-width"
                  type="button"
                  onClick={() => onRecheck(selected.run.claimId)}
                >
                  Review correction details
                </button>
              </section>

              <section className="audit-preview" id="audit" aria-labelledby="audit-title">
                <div className="audit-heading">
                  <h3 id="audit-title">Recent audit activity</h3>
                  <History size={16} aria-hidden="true" />
                </div>
                {selected.decisions.length ? (
                  <ol>
                    {selected.decisions.slice(-3).map((decision) => (
                      <li key={decision.decisionId}>
                        <span>{decision.actor}</span>
                        <strong>{titleCase(decision.action)}</strong>
                        <time dateTime={decision.createdAt}>{relativeActivity(decision.createdAt)}</time>
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p>No reviewer decisions recorded for this version.</p>
                )}
              </section>
            </>
          ) : (
            <div className="empty-state compact">
              <Sparkles size={24} aria-hidden="true" />
              <p>Explanations appear after a claim is selected.</p>
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}

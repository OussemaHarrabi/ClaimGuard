// ClaimGuard AI — reviewer interface: the rendering module.
//
// UNTRUSTED-DATA POLICY (read this before editing)
// ------------------------------------------------
// These fields are UNTRUSTED DATA and are never markup:
//
//   * claim `notes` and attachment `text` (they reach this module inside the
//     engine's evidence values, e.g. `/attachments/0/text` or `/notes`),
//   * rule `explanation` and `corrective_action`,
//   * evidence `path` / `value`, claim ids, rule ids, actor and reason strings
//     typed by a reviewer, and every API error body.
//
// Every one of them is written with `document.createTextNode` (via `el` below),
// so a payload such as `<script>alert(1)</script>` is displayed as those
// characters and can never become an element, an attribute or an event handler.
// This module never builds HTML from a string: there is no `innerHTML`,
// `outerHTML`, `insertAdjacentHTML` or `document.write` anywhere in it, and
// `tests/review_ui/dom_shim.mjs` seals the nodes it creates so that assigning
// `innerHTML` raises instead of silently doing nothing.
//
// The DOM is passed in as `doc` rather than reached for as a global, so the
// renderers are pure functions of (document-like, data) and can be exercised by
// the tests under Node without a browser.

/**
 * What each pack status means to a reviewer. This is the single source for the
 * status legend, so a status can never be styled as a pass without its meaning
 * being stated next to it. NOT_IMPLEMENTED is never a PASS.
 */
export const STATUS_MEANINGS = {
  PASS: "This specific check passed on the supplied data. It is not payer approval.",
  FAIL: "The check found an issue. A human decides what happens next.",
  UNABLE_TO_ASSESS:
    "The check could not decide from the supplied data. A human must assess it.",
  NOT_APPLICABLE: "The rule does not apply to this claim. It is not a pass.",
  NOT_IMPLEMENTED:
    "This check has not run. The claim cannot be considered fully checked.",
};

/** The four decisions the API accepts, in the pack's order (behaviour 5). */
export const REVIEW_ACTIONS = [
  ["confirm_issue", "Confirm issue"],
  ["dismiss_with_reason", "Dismiss with reason"],
  ["request_information", "Request information"],
  ["mark_corrected_for_recheck", "Mark corrected for recheck"],
];

const STATUS_NAMES = Object.keys(STATUS_MEANINGS);

/**
 * One value as display text. Strings are shown as they are; everything else is
 * shown as JSON, because evidence values include whole arrays and objects
 * (the `/lines` array, the `/attachments` inventory).
 */
export function formatValue(value) {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** A class suffix for a status, restricted to the statuses the pack defines. */
export function statusClass(status) {
  return STATUS_NAMES.includes(status) ? `status-${status}` : "status-UNKNOWN";
}

/** An element whose text is written as text — the only way this module writes text. */
export function el(doc, tag, className, text) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.append(doc.createTextNode(String(text)));
  return node;
}

/** `path = value`, with the ORIGINAL value the engine observed. */
export function renderEvidence(doc, evidence) {
  const box = el(doc, "div", "evidence");
  box.append(el(doc, "p", "evidence-caption", "Evidence (original values from the submitted claim):"));
  if (!evidence || evidence.length === 0) {
    box.append(el(doc, "p", "muted", "No evidence pointers for this check."));
    return box;
  }
  for (const entry of evidence) {
    const row = el(doc, "div", "evidence-row");
    row.append(el(doc, "code", "evidence-path", entry.path));
    row.append(el(doc, "span", "evidence-equals", " = "));
    row.append(el(doc, "code", "evidence-value", formatValue(entry.value)));
    box.append(row);
  }
  return box;
}

/** The status badge, plus the meaning of that status for a reviewer. */
export function renderStatus(doc, status) {
  const box = el(doc, "span", "status-box");
  box.append(el(doc, "span", `badge ${statusClass(status)}`, status));
  box.append(
    el(doc, "span", "status-meaning", STATUS_MEANINGS[status] || "Unknown status from the API."),
  );
  return box;
}

/** The status legend: each status with the meaning a reviewer must read with it. */
export function renderLegend(doc) {
  const box = el(doc, "div", "legend");
  for (const status of STATUS_NAMES) {
    const row = el(doc, "div", "legend-row");
    row.append(el(doc, "span", `badge ${statusClass(status)}`, status));
    row.append(el(doc, "span", "legend-meaning", STATUS_MEANINGS[status]));
    box.append(row);
  }
  return box;
}

/** One of the run's 15 records, with its reviewer state and its decision form. */
export function renderFinding(doc, record, options) {
  const settings = options || {};
  const article = el(doc, "article", `finding ${statusClass(record.status)}`);

  const head = el(doc, "div", "finding-head");
  head.append(el(doc, "strong", "finding-rule", record.rule_id));
  head.append(renderStatus(doc, record.status));
  head.append(el(doc, "span", `severity severity-${record.severity}`, `severity: ${record.severity}`));
  const review = settings.review;
  head.append(
    el(
      doc,
      "span",
      "review-state",
      review
        ? `review: ${review.status}${review.actor ? ` by ${review.actor}` : ""}` +
            (review.unresolved ? " (unresolved)" : "")
        : "review: not loaded",
    ),
  );
  article.append(head);

  article.append(el(doc, "p", "explanation", record.explanation));
  article.append(
    el(doc, "p", "corrective", `Corrective action: ${record.corrective_action || "none supplied"}`),
  );
  article.append(renderEvidence(doc, record.evidence));

  const meta = el(doc, "p", "meta");
  meta.append(
    el(
      doc,
      "span",
      "muted",
      `affected lines: ${record.affected_line_ids.length ? record.affected_line_ids.join(", ") : "none"} | ` +
        `source: ${record.rule_source} | ` +
        `human review required: ${record.requires_human_review ? "yes" : "no"} | ` +
        `confidence: ${formatValue(record.confidence)} (${record.confidence_kind}) | ` +
        `method: ${record.method} | result review_status: ${record.review_status}`,
    ),
  );
  article.append(meta);

  article.append(renderDecisionForm(doc, record, settings.onDecide));
  return article;
}

/** The four decision buttons plus the reason box for one finding. */
export function renderDecisionForm(doc, record, onDecide) {
  const form = el(doc, "div", "decision-form");
  form.append(
    el(
      doc,
      "p",
      "muted",
      "Record a decision for " +
        record.rule_id +
        ". The actor (from the reviewer field above) and the reason are both required by the API: " +
        "leave either blank and the API's own validation error is shown, unedited.",
    ),
  );
  const reason = doc.createElement("textarea");
  reason.className = "decision-reason";
  reason.setAttribute("rows", "2");
  reason.setAttribute("aria-label", `Reason for the decision on ${record.rule_id}`);
  reason.setAttribute("placeholder", "Reason (recorded verbatim in the append-only ledger)");
  form.append(reason);

  const buttons = el(doc, "div", "decision-actions");
  for (const [action, label] of REVIEW_ACTIONS) {
    const button = el(doc, "button", `action action-${action}`, label);
    button.setAttribute("type", "button");
    button.addEventListener("click", () => {
      if (typeof onDecide === "function") {
        onDecide({ rule_id: record.rule_id, action: action, reason: reason.value });
      }
    });
    buttons.append(button);
  }
  form.append(buttons);
  return form;
}

/** The queue's counts: what the reviewer is looking at, and what is still owed. */
export function renderCounts(doc, counts) {
  const box = el(doc, "div", "counts");
  const headline = el(doc, "p", "counts-headline");
  headline.append(
    el(
      doc,
      "span",
      "counts-unresolved",
      `${counts.unresolved} unresolved check(s) still need a decision, of ${counts.findings} finding(s) shown`,
    ),
  );
  headline.append(
    el(doc, "span", "counts-resolved", `${counts.resolved} resolved (confirmed, dismissed or corrected)`),
  );
  box.append(headline);

  const table = el(doc, "table", "counts-table");
  const head = el(doc, "tr");
  head.append(el(doc, "th", "", "by rule status"));
  head.append(el(doc, "th", "", "count"));
  table.append(head);
  for (const status of STATUS_NAMES) {
    const row = el(doc, "tr");
    row.append(el(doc, "td", "", status));
    row.append(el(doc, "td", "", String(counts.by_rule_status[status] || 0)));
    table.append(row);
  }
  box.append(table);

  const other = el(doc, "p", "counts-other");
  other.append(
    el(doc, "span", "muted", `by severity: ${JSON.stringify(counts.by_severity)} | `),
  );
  other.append(el(doc, "span", "muted", `by review status: ${JSON.stringify(counts.by_review_status)}`));
  box.append(other);
  return box;
}

/** The per-claim rollup: the unresolved count stated plainly, per claim. */
export function renderClaims(doc, claims, onOpen) {
  const box = el(doc, "div", "claims");
  box.append(el(doc, "h3", "", "Claims in this listing (latest version each)"));
  if (!claims || claims.length === 0) {
    box.append(el(doc, "p", "muted", "No claims match these filters."));
    return box;
  }
  const table = el(doc, "table", "claims-table");
  const head = el(doc, "tr");
  for (const label of ["claim", "version", "findings", "unresolved", "latest decision", ""]) {
    head.append(el(doc, "th", "", label));
  }
  table.append(head);
  for (const claim of claims) {
    const row = el(doc, "tr");
    row.append(el(doc, "td", "", claim.claim_id));
    row.append(el(doc, "td", "", String(claim.version)));
    row.append(el(doc, "td", "", String(claim.findings)));
    row.append(el(doc, "td", "unresolved-count", String(claim.unresolved)));
    row.append(el(doc, "td", "", claim.latest_decision_at || "no decision yet"));
    const cell = el(doc, "td");
    const open = el(doc, "button", "open-claim", "Open this claim");
    open.setAttribute("type", "button");
    open.addEventListener("click", () => {
      if (typeof onOpen === "function") onOpen(claim.run_id, claim.claim_id);
    });
    cell.append(open);
    row.append(cell);
    table.append(row);
  }
  box.append(table);
  return box;
}

/** The filtered findings, each one openable. */
export function renderQueueItems(doc, items, onOpen) {
  const box = el(doc, "div", "queue-items");
  box.append(el(doc, "h3", "", "Findings in this listing"));
  if (!items || items.length === 0) {
    box.append(el(doc, "p", "muted", "No findings match these filters."));
    return box;
  }
  for (const item of items) {
    const row = el(doc, "div", "queue-item");
    row.append(el(doc, "span", "badge " + statusClass(item.record.status), item.record.status));
    row.append(el(doc, "strong", "", item.claim_id));
    row.append(el(doc, "span", "muted", `v${item.version} ${item.run_id} ${item.record.rule_id}`));
    row.append(
      el(
        doc,
        "span",
        "muted",
        `review: ${item.review.status}${item.review.unresolved ? " (unresolved)" : ""}` +
          ` | needs attention: ${item.needs_attention ? "yes" : "no"}`,
      ),
    );
    const open = el(doc, "button", "open-claim", "Open claim");
    open.setAttribute("type", "button");
    open.addEventListener("click", () => {
      if (typeof onOpen === "function") onOpen(item.run_id, item.claim_id);
    });
    row.append(open);
    box.append(row);
  }
  return box;
}

/** The run's identity: what produced these results, and which version this is. */
export function renderRunHeader(doc, run) {
  const box = el(doc, "div", "run-header");
  box.append(el(doc, "h3", "", `${run.claim_id} — version ${run.version}`));
  const list = el(doc, "dl", "run-identity");
  const facts = [
    ["run", run.run_id],
    ["input hash", run.input_hash],
    ["rule version", run.rule_version],
    ["model version", run.model_version],
    ["prompt version", run.prompt_version],
    ["initiated by", run.initiated_by],
    ["created", run.created_at],
    ["supersedes", run.supersedes_run_id || "nothing (this is the first version)"],
  ];
  for (const [label, value] of facts) {
    list.append(el(doc, "dt", "", label));
    list.append(el(doc, "dd", "", value));
  }
  box.append(list);
  return box;
}

/** Every version of this claim the reviewer has open in this page, each viewable. */
export function renderVersions(doc, versions, onOpen) {
  const box = el(doc, "div", "versions");
  box.append(el(doc, "h3", "", "Run versions open in this page"));
  for (const entry of versions) {
    const row = el(doc, "div", "version-row");
    row.append(el(doc, "strong", "", `v${entry.version}`));
    row.append(el(doc, "span", "muted", ` ${entry.run_id}`));
    row.append(
      el(doc, "span", "muted", entry.supersedes_run_id ? ` (supersedes ${entry.supersedes_run_id})` : ""),
    );
    const open = el(doc, "button", "open-claim", "View this run's 15 results");
    open.setAttribute("type", "button");
    open.addEventListener("click", () => {
      if (typeof onOpen === "function") onOpen(entry.run_id, entry.claim_id);
    });
    row.append(open);
    box.append(row);
  }
  return box;
}

/** The decision history of one run: what was recorded, by whom, and why. */
export function renderDecisions(doc, history) {
  const box = el(doc, "div", "decisions");
  box.append(el(doc, "h3", "", "Decision history for this run (append-only)"));
  if (!history || history.entries.length === 0) {
    box.append(el(doc, "p", "muted", "No decision has been recorded against this run yet."));
    return box;
  }
  const table = el(doc, "table", "decisions-table");
  const head = el(doc, "tr");
  for (const label of ["rule", "action", "actor", "reason", "original status", "recorded at", "state"]) {
    head.append(el(doc, "th", "", label));
  }
  table.append(head);
  for (const entry of history.entries) {
    const event = entry.decision.event;
    const row = el(doc, "tr");
    row.append(el(doc, "td", "", event.rule_id));
    row.append(el(doc, "td", "", event.action));
    row.append(el(doc, "td", "", event.actor));
    row.append(el(doc, "td", "", event.reason));
    row.append(el(doc, "td", "", event.original_status));
    row.append(el(doc, "td", "", event.created_at));
    row.append(el(doc, "td", "", `${entry.review.status}${entry.review.unresolved ? " (unresolved)" : ""}`));
    table.append(row);
  }
  box.append(table);
  return box;
}

/** The reviewer's current state per rule, derived from the decision history. */
export function latestReviewByRule(history) {
  const byRule = {};
  if (!history || !history.entries) return byRule;
  for (const entry of history.entries) {
    byRule[entry.decision.event.rule_id] = entry.review;
  }
  return byRule;
}

/** A message for the reviewer. `detail` may be an API error body — shown as text. */
export function renderNotice(doc, message, kind, detail) {
  const box = el(doc, "div", `notice notice-${kind || "info"}`);
  box.append(el(doc, "p", "", message));
  if (detail !== undefined && detail !== null) {
    box.append(el(doc, "pre", "notice-detail", formatValue(detail)));
  }
  return box;
}

/**
 * The API's own refusal, shown as it arrived. A 422 (a blank actor or reason, a
 * malformed envelope) is never replaced by a friendlier client-side message: the
 * reviewer sees the status, the error name and the body the API sent.
 */
export function renderApiError(doc, status, body, context) {
  const box = el(doc, "div", "api-error");
  box.append(el(doc, "p", "api-error-head", `${context || "The API refused this request"} — HTTP ${status}`));
  box.append(el(doc, "pre", "api-error-body", formatValue(body)));
  return box;
}

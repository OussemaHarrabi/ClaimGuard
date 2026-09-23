// ClaimGuard AI — reviewer interface: the wiring.
//
// This file fetches from the review API and puts the answers on the page. It
// builds no HTML from strings: every node comes from `render.mjs`, which writes
// all untrusted values as text (see its untrusted-data policy). The only values
// this file reads from the page are the reviewer's own inputs (actor, reason,
// filters, the pasted corrected envelope).
//
// The page has NO authentication: the actor field is self-declared, exactly as
// the pack's own review page describes its reviewer identity.

import * as render from "./render.mjs";

const state = {
  /** The run currently displayed, and every version opened in this page. */
  current: null,
  versions: [],
};

const byId = (id) => document.getElementById(id);

/** One API call. Returns the status and the parsed body; never throws on 4xx. */
async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  let body = text;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    // Not JSON: keep the raw text so the reviewer sees exactly what arrived.
  }
  return { ok: response.ok, status: response.status, body: body };
}

/** The API's own error, shown unedited (a 422 is never papered over). */
function showError(container, context, result) {
  container.replaceChildren(render.renderApiError(document, result.status, result.body, context));
}

function filters() {
  const query = new URLSearchParams();
  const status = byId("filter-status").value;
  const severity = byId("filter-severity").value;
  const rule = byId("filter-rule").value;
  if (status) query.set("status", status);
  if (severity) query.set("severity", severity);
  if (rule) query.set("rule_id", rule);
  if (byId("filter-include-all").checked) query.set("include_all", "true");
  return query;
}

async function refreshQueue() {
  const result = await api(`/v1/queue?${filters().toString()}`);
  const status = byId("queue-status");
  if (!result.ok) {
    status.replaceChildren();
    showError(byId("queue-error"), "The queue could not be read", result);
    return;
  }
  byId("queue-error").replaceChildren();
  const queue = result.body;
  status.replaceChildren(
    render.renderNotice(
      document,
      `Filters applied: ${JSON.stringify(queue.filters)} — counts below describe the ${queue.counts.findings} finding(s) shown.`,
      "info",
    ),
  );
  byId("queue-counts").replaceChildren(render.renderCounts(document, queue.counts));
  byId("queue-claims").replaceChildren(render.renderClaims(document, queue.claims, openClaim));
  byId("queue-items").replaceChildren(render.renderQueueItems(document, queue.items, openClaim));
}

/** Open one claim version: its 15 results, its identity and its decision history. */
async function openClaim(runId, claimId) {
  const previous = state.current;
  const results = await api(`/v1/runs/${encodeURIComponent(runId)}/results`);
  if (!results.ok) {
    showError(byId("detail-error"), `Run ${runId} could not be read`, results);
    return;
  }
  byId("detail-error").replaceChildren();
  const run = results.body.run;
  state.current = { run_id: run.run_id, claim_id: run.claim_id, version: run.version };

  if (!state.versions.some((entry) => entry.run_id === run.run_id)) {
    state.versions.push({
      run_id: run.run_id,
      claim_id: run.claim_id,
      version: run.version,
      supersedes_run_id: run.supersedes_run_id,
    });
  }

  const history = await api(`/v1/runs/${encodeURIComponent(runId)}/decisions`);
  const entries = history.ok ? history.body : { run_id: runId, entries: [] };
  const reviews = render.latestReviewByRule(entries);
  // The API's own provenance for each explanation, served beside the records
  // (`explanations`), keyed here by rule id so a finding can show whether the
  // text a reviewer is reading is deterministic or model-assisted.
  const provenanceByRule = {};
  for (const entry of results.body.explanations || []) {
    provenanceByRule[entry.rule_id] = entry;
  }

  byId("detail-meta").replaceChildren(
    render.renderRunHeader(document, run),
    render.renderNotice(
      document,
      "The reviewer field below is self-declared: this page has no login. It is sent as the decision's actor, and the API refuses a blank actor or a blank reason — leave either empty to see that refusal.",
      "info",
    ),
    render.renderVersions(document, state.versions, openClaim),
  );

  const findings = document.createElement("div");
  findings.className = "findings";
  for (const record of results.body.results) {
    findings.append(
      render.renderFinding(document, record, {
        review: reviews[record.rule_id],
        explanation: provenanceByRule[record.rule_id],
        onDecide: decide,
      }),
    );
  }
  byId("detail-findings").replaceChildren(findings);

  byId("decisions").replaceChildren(render.renderDecisions(document, entries));
  byId("recheck-claim-id").replaceChildren(document.createTextNode(run.claim_id));
  if (!previous || previous.claim_id !== run.claim_id) {
    // A different claim: the previously pasted envelope belongs to another claim.
    byId("recheck-claim").value = "";
    byId("recheck-result").replaceChildren();
  }
}

/** Record one of the pack's four decisions against the displayed run. */
async function decide({ rule_id, action, reason }) {
  const target = state.current;
  if (!target) return;
  const actor = byId("detail-actor").value;
  const result = await api(`/v1/runs/${encodeURIComponent(target.run_id)}/decisions`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ rule_id, action, actor, reason }),
  });
  const box = byId("decision-result");
  if (!result.ok) {
    showError(box, `The decision on ${rule_id} was refused`, result);
    return;
  }
  box.replaceChildren(
    render.renderNotice(
      document,
      `Recorded ${action} for ${rule_id} on ${target.run_id} (HTTP ${result.status}); the finding's review state is now ${result.body.review.status}${result.body.review.unresolved ? " (still unresolved)" : ""}. Audit chain hash: ${result.body.audit.chain_hash}`,
      "ok",
    ),
  );
  await openClaim(target.run_id, target.claim_id);
  await refreshQueue();
}

/** Submit a corrected envelope as a NEW version of the displayed claim. */
async function recheck() {
  const target = state.current;
  if (!target) return;
  const box = byId("recheck-result");
  const raw = byId("recheck-claim").value;
  let envelope;
  try {
    envelope = JSON.parse(raw);
  } catch (error) {
    // A client-side parse failure is labelled as one; it is not the API's answer.
    box.replaceChildren(
      render.renderNotice(
        document,
        "This page could not parse the corrected envelope as JSON, so nothing was sent to the API: " +
          String(error),
        "error",
      ),
    );
    return;
  }
  const result = await api(`/v1/claims/${encodeURIComponent(target.claim_id)}/recheck`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ claim: envelope, actor: byId("recheck-actor").value }),
  });
  if (!result.ok) {
    showError(box, "The recheck was refused", result);
    return;
  }
  const run = result.body.run;
  state.versions.push({
    run_id: run.run_id,
    claim_id: run.claim_id,
    version: run.version,
    supersedes_run_id: run.supersedes_run_id,
  });
  box.replaceChildren(
    render.renderNotice(
      document,
      `The recheck produced version ${run.version} as ${run.run_id} (HTTP ${result.status}), superseding ${run.supersedes_run_id}. Version ${target.version} (${target.run_id}) is unchanged and still viewable — nothing in this page replaced it.`,
      "ok",
    ),
    render.renderVersions(document, state.versions, openClaim),
  );
  await refreshQueue();
}

byId("filters").addEventListener("submit", (event) => {
  event.preventDefault();
  refreshQueue();
});
byId("recheck-submit").addEventListener("click", recheck);

// The legend is rendered from the same table the badges use, so a status can
// never be displayed without the meaning a reviewer has to read with it.
byId("legend").replaceChildren(render.renderLegend(document));
refreshQueue();

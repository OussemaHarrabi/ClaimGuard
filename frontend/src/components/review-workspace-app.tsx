"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { Braces, CircleAlert, X } from "lucide-react";
import { Input } from "./ui/input";
import { editableEvidencePaths, readPointer, updatePointer } from "../lib/claim-editor";

import { ReviewCockpit, type ReviewWorkspace } from "./review-cockpit";
import { demoClaim, demoWorkspace } from "../lib/demo-workspace";
import {
  buildReviewWorkspace,
  emptyWorkspace,
  getClaimEnvelope,
  getDecisionHistory,
  getQueue,
  getRunDetails,
  recordDecision,
  recheckClaim,
  type QueueResponse,
} from "../lib/review-api";

const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export function ReviewWorkspaceApp({ reviewer, scope, includeAll = false }: { reviewer: string; scope: "mine" | "team"; includeAll?: boolean }) {
  const [workspace, setWorkspace] = useState<ReviewWorkspace>(emptyWorkspace);
  const [queue, setQueue] = useState<QueueResponse | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [demo, setDemo] = useState(DEMO_MODE);
  const [correction, setCorrection] = useState<{ claimId: string; runId: string; text: string } | null>(null);

  const loadSelection = useCallback(async (currentQueue: QueueResponse, runId: string) => {
    const [details, history] = await Promise.all([
      getRunDetails(runId),
      getDecisionHistory(runId),
    ]);
    setWorkspace(buildReviewWorkspace(currentQueue, details, history));
  }, []);

  const load = useCallback(async (preferredRunId?: string) => {
    setBusy(true);
    setError(null);
    try {
      if (DEMO_MODE) {
        setWorkspace(demoWorkspace);
        setDemo(true);
        return;
      }
      const nextQueue = await getQueue(scope, undefined, includeAll);
      setQueue(nextQueue);
      setDemo(false);
      const requestedRunId = preferredRunId ?? new URLSearchParams(window.location.search).get("run");
      const runId = nextQueue.claims.find((claim) => claim.run_id === requestedRunId)?.run_id ?? nextQueue.claims[0]?.run_id;
      if (runId) await loadSelection(nextQueue, runId);
      else setWorkspace(buildReviewWorkspace(nextQueue, null, null));
    } catch (cause) {
      setWorkspace(emptyWorkspace());
      setError(cause instanceof Error ? cause.message : "The review workspace could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, [includeAll, loadSelection, scope]);

  useEffect(() => {
    const bootstrap = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(bootstrap);
  }, [load]);

  const selectClaim = useCallback(async (runId: string) => {
    if (demo) {
      setWorkspace(demoWorkspace);
      return;
    }
    if (!queue) return;
    setBusy(true);
    setError(null);
    try {
      await loadSelection(queue, runId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The claim details could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, [demo, loadSelection, queue]);

  const decide = useCallback(async (ruleId: string, action: string, reason: string) => {
    const runId = workspace.selected?.run.runId;
    if (!runId) return;
    if (demo) {
      setError("Demo mode is read-only. Start the API stack to record reviewer decisions.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await recordDecision(runId, { ruleId, action, actor: reviewer, reason });
      await load(runId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The decision could not be recorded.");
      setBusy(false);
    }
  }, [demo, load, reviewer, workspace.selected?.run.runId]);

  const openCorrection = useCallback(async (claimId: string) => {
    const runId = workspace.selected?.run.runId;
    if (!runId) return;
    setBusy(true);
    setError(null);
    try {
      const claim = demo ? demoClaim : (await getClaimEnvelope(runId)).claim;
      setCorrection({ claimId, runId, text: JSON.stringify(claim, null, 2) });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The stored claim could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, [demo, workspace.selected?.run.runId]);

  const submitCorrection = useCallback(async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!correction) return;
    setError(null);
    let claim: Record<string, unknown>;
    try {
      claim = JSON.parse(correction.text) as Record<string, unknown>;
    } catch {
      setError("The corrected claim is not valid JSON.");
      return;
    }
    if (claim.claim_id !== correction.claimId) {
      setError(`The corrected claim_id must remain ${correction.claimId}.`);
      return;
    }
    if (demo) {
      setError("Demo mode is read-only. Start the API stack to submit a corrected version.");
      return;
    }
    setBusy(true);
    try {
      const created = await recheckClaim(correction.claimId, claim, reviewer);
      setCorrection(null);
      await load(created.run.run_id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The corrected claim could not be rechecked.");
      setBusy(false);
    }
  }, [correction, demo, load, reviewer]);

  const statusLabel = useMemo(() => demo ? "Demo data · read-only" : "Live review API", [demo]);
  let parsedCorrection: Record<string, unknown> | null = null;
  if (correction) {
    try { parsedCorrection = JSON.parse(correction.text) as Record<string, unknown>; }
    catch { /* The advanced editor can repair invalid JSON. */ }
  }
  const correctionFields = correction && parsedCorrection
    ? editableEvidencePaths(workspace.selected?.findings ?? [], parsedCorrection)
    : [];

  function editEvidence(path: string, value: string) {
    if (!correction) return;
    try {
      setCorrection({ ...correction, text: updatePointer(correction.text, path, value) });
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "This field could not be edited.");
    }
  }

  return (
    <>
      <div className={`environment-badge${demo ? " demo" : ""}`}>{statusLabel}</div>
      <ReviewCockpit
        workspace={workspace}
        busy={busy}
        error={error}
        reviewer={reviewer}
        onSelectClaim={(runId) => void selectClaim(runId)}
        onRefresh={() => void load(workspace.selected?.run.runId)}
        onRecordDecision={(ruleId, action, reason) => void decide(ruleId, action, reason)}
        onRecheck={(claimId) => void openCorrection(claimId)}
      />

      {correction ? (
        <div className="drawer-backdrop" role="presentation" onMouseDown={() => setCorrection(null)}>
          <section
            className="correction-drawer"
            role="dialog"
            aria-modal="true"
            aria-labelledby="correction-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header>
              <div>
                <p className="eyebrow">New immutable version</p>
                <h2 id="correction-title">Correct {correction.claimId}</h2>
              </div>
              <button className="icon-button" type="button" aria-label="Close correction editor" onClick={() => setCorrection(null)}>
                <X size={18} />
              </button>
            </header>
            <p className="drawer-boundary">
              <CircleAlert size={17} /> The original run stays unchanged. Saving creates a new version and reruns all deterministic checks.
            </p>
            <form onSubmit={submitCorrection}>
              <section className="guided-fields" aria-labelledby="guided-fields-title">
                <h3 id="guided-fields-title">Step 1: verify the flagged values</h3>
                <p>These fields come from non-passing checks. Compare each value with the clinic documents. Change only a documented error. If a fact is missing, close this form and request information instead.</p>
                {correctionFields.length ? <div className="guided-field-grid">{correctionFields.map((path) => {
                  const current = readPointer(parsedCorrection, path);
                  const numeric = typeof current === "number" || (current === null && /(?:amount|price|quantity|total)$/i.test(path));
                  return <label key={path}><span>{path.slice(1).replaceAll("/", " → ").replaceAll("_", " ")}</span><Input type={numeric ? "number" : "text"} step={numeric ? "any" : undefined} value={current === null ? "" : String(current)} onChange={(event) => editEvidence(path, event.target.value)} /></label>;
                })}</div> : <p>No scalar evidence fields are available. Use the advanced editor below.</p>}
              </section>
              <p className="correction-submit-help">Step 2: create a new claim version. ClaimGuard will rerun all deterministic checks; the original version remains in the audit history.</p>
              <details className="advanced-json" open={!parsedCorrection}>
                <summary><Braces size={16} /> Advanced: full claim JSON</summary>
                <label className="json-editor">
                  <span>Corrected synthetic claim JSON</span>
                  <textarea
                    value={correction.text}
                    spellCheck={false}
                    onChange={(event) => setCorrection({ ...correction, text: event.target.value })}
                  />
                </label>
              </details>
              <div className="drawer-actions">
                <button className="secondary-button" type="button" onClick={() => setCorrection(null)}>Cancel</button>
                <button className="primary-button" type="submit" disabled={busy}>Create version &amp; recheck</button>
              </div>
            </form>
          </section>
        </div>
      ) : null}
    </>
  );
}

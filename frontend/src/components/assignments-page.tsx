"use client";

import { useCallback, useEffect, useState } from "react";

type Claim = { claim_id: string; run_id: string; unresolved: number };
type TeamMember = { user_id: string; email: string; role: string };
type Assignment = { claim_id: string; reviewer_user_id: string };

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail ?? `Request failed (${response.status}).`);
  }
  return await response.json() as T;
}

export function AssignmentsPage({ claimPage = "team-queue" }: { claimPage?: "team-queue" | "all-claims" }) {
  const [claims, setClaims] = useState<Claim[]>([]);
  const [reviewers, setReviewers] = useState<TeamMember[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [selection, setSelection] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const [queue, team, assigned] = await Promise.all([
        fetch("/v1/queue?include_all=true", { cache: "no-store" }).then((response) => readJson<{ claims: Claim[] }>(response)),
        fetch("/v1/team", { cache: "no-store" }).then((response) => readJson<TeamMember[]>(response)),
        fetch("/v1/assignments", { cache: "no-store" }).then((response) => readJson<Assignment[]>(response)),
      ]);
      setClaims(queue.claims);
      setReviewers(team.filter((member) => member.role === "rcm_reviewer" || member.role === "rcm_lead"));
      setAssignments(assigned);
      setSelection(Object.fromEntries(assigned.map((assignment) => [assignment.claim_id, assignment.reviewer_user_id])));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Assignments could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function assign(claimId: string) {
    const reviewerUserId = selection[claimId];
    if (!reviewerUserId) return;
    setSaving(claimId);
    setError(null);
    setNotice(null);
    try {
      const saved = await readJson<Assignment>(await fetch("/v1/assignments", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ claim_id: claimId, reviewer_user_id: reviewerUserId }),
      }));
      setAssignments((current) => [...current.filter((item) => item.claim_id !== claimId), saved]);
      setNotice(`Assignment saved for ${claimId}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Assignment could not be saved.");
    } finally {
      setSaving(null);
    }
  }

  return (
    <section className="clinic-page" aria-busy={busy}>
      <header className="clinic-page-heading"><div><p className="eyebrow">Workload routing</p><h1>Assignments</h1></div><button type="button" className="secondary-button" onClick={() => void load()} disabled={busy}>Refresh</button></header>
      <p>Assign each claim to an active reviewer. The reviewer will see it in My Queue.</p>
      {error ? <p role="alert" className="clinic-error">{error}</p> : null}
      {notice ? <p role="status" className="clinic-success">{notice}</p> : null}
      {busy ? <p>Loading claims and staff…</p> : null}
      {!busy && claims.length === 0 ? <p>No claims need routing yet.</p> : null}
      {!busy && claims.length > 0 ? (
        <div className="clinic-table-wrap"><table className="clinic-table"><thead><tr><th>Claim</th><th>Open findings</th><th>Current reviewer</th><th>Assign to</th><th>Action</th></tr></thead><tbody>
          {claims.map((claim) => {
            const current = assignments.find((item) => item.claim_id === claim.claim_id);
            return <tr key={claim.claim_id}>
              <td><a href={`/workspace/${claimPage}?run=${encodeURIComponent(claim.run_id)}`}>{claim.claim_id}</a></td>
              <td>{claim.unresolved}</td>
              <td>{reviewers.find((member) => member.user_id === current?.reviewer_user_id)?.email ?? "Unassigned"}</td>
              <td><select aria-label={`Reviewer for ${claim.claim_id}`} value={selection[claim.claim_id] ?? ""} onChange={(event) => setSelection((old) => ({ ...old, [claim.claim_id]: event.target.value }))}>
                <option value="">Select reviewer</option>
                {reviewers.map((member) => <option key={member.user_id} value={member.user_id}>{member.email}</option>)}
              </select></td>
              <td><button type="button" className="primary-button" disabled={!selection[claim.claim_id] || saving === claim.claim_id} onClick={() => void assign(claim.claim_id)}>{saving === claim.claim_id ? "Saving…" : `Assign ${claim.claim_id}`}</button></td>
            </tr>;
          })}
        </tbody></table></div>
      ) : null}
    </section>
  );
}

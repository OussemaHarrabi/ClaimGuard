"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Card } from "./ui/card";

type Row = Record<string, unknown>;

async function json<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => ({})) as T & { detail?: string };
  if (!response.ok) throw new Error(body.detail ?? `Request failed (${response.status}).`);
  return body;
}

function useRemote<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try { setData(await json<T>(await fetch(path, { cache: "no-store" }))); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "The data could not be loaded."); }
    finally { setBusy(false); }
  }, [path]);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);
  return { data, busy, error, setError, load };
}

function display(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function DataTable({ rows, empty = "No records yet." }: { rows: Row[]; empty?: string }) {
  if (!rows.length) return <p className="clinic-empty">{empty}</p>;
  const columns = Object.keys(rows[0]);
  return <div className="clinic-table-wrap"><table className="clinic-table"><thead><tr>{columns.map((key) => <th key={key}>{key.replaceAll("_", " ")}</th>)}</tr></thead><tbody>
    {rows.map((row, index) => <tr key={String(row.id ?? row.run_id ?? row.job_id ?? row.request_id ?? row.escalation_id ?? index)}>{columns.map((key) => <td key={key}>{display(row[key])}</td>)}</tr>)}
  </tbody></table></div>;
}

function Metrics({ values }: { values: Row }) {
  return <div className="clinic-metrics">{Object.entries(values).map(([key, value]) => <Card key={key}><span>{key.replaceAll("_", " ")}</span><strong>{display(value)}</strong></Card>)}</div>;
}

const REPORTS: Record<string, { title: string; eyebrow: string; description: string; endpoint: string }> = {
  activity: { title: "Activity", eyebrow: "Review trail", description: "Clinic review actions, newest first.", endpoint: "/v1/activity" },
  "review-quality": { title: "Review Quality", eyebrow: "Team performance", description: "Recorded decisions and resolved collaboration work.", endpoint: "/v1/review-quality" },
  overview: { title: "Overview", eyebrow: "Clinic operations", description: "Live claim, assignment, request, escalation, and intake counts.", endpoint: "/v1/overview" },
  analytics: { title: "Analytics", eyebrow: "Clinic reporting", description: "Daily run volumes and finding status distribution from persisted checks.", endpoint: "/v1/analytics" },
  audit: { title: "Audit", eyebrow: "Traceability", description: "Clinic-scoped run provenance and hash-chain references.", endpoint: "/v1/audit" },
  "intake-operations": { title: "Intake Jobs", eyebrow: "Service monitoring", description: "Job counts by status. Document and claim content is excluded.", endpoint: "/v1/intake-jobs/operations" },
  versions: { title: "Versions", eyebrow: "Version inventory", description: "Rule, model, and prompt versions observed in this clinic's runs.", endpoint: "/v1/versions" },
  "audit-integrity": { title: "Audit Integrity", eyebrow: "Tamper evidence", description: "Verify every event link in the shared immutable ledger, without exposing claim content.", endpoint: "/v1/audit-integrity" },
};

export function ClinicReportPage({ page }: { page: string }) {
  const report = REPORTS[page];
  const { data, busy, error, load } = useRemote<unknown>(report.endpoint);
  const sections = data && !Array.isArray(data) ? Object.entries(data as Row) : [];
  const scalarReport = sections.length > 0 && sections.every(([, value]) => !Array.isArray(value) && (value === null || typeof value !== "object"));
  return <section className="clinic-page" aria-busy={busy}>
    <header className="clinic-page-heading"><div><p className="eyebrow">{report.eyebrow}</p><h1>{report.title}</h1></div><button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}>Refresh</button></header>
    <p>{report.description}</p>
    {error ? <p role="alert" className="clinic-error">{error}</p> : null}
    {busy ? <p>Loading live data…</p> : null}
    {!busy && Array.isArray(data) ? <DataTable rows={data as Row[]} /> : null}
    {!busy && scalarReport ? <Metrics values={data as Row} /> : null}
    {!busy && !scalarReport ? sections.map(([key, value]) => <section className="clinic-report-section" key={key}>
      <h2>{key.replaceAll("_", " ")}</h2>
      {Array.isArray(value) ? <DataTable rows={value as Row[]} /> : value && typeof value === "object" ? <Metrics values={value as Row} /> : <Metrics values={{ [key]: value }} />}
    </section>) : null}
  </section>;
}

type WorkItem = { request_id?: string; escalation_id?: string; run_id: string; status: string; message?: string; reason?: string; response?: string; resolution?: string; created_at: string };

export function WorkItemsPage({ kind }: { kind: "requests" | "escalations" }) {
  const { data, busy, error, setError, load } = useRemote<WorkItem[]>(`/v1/${kind}`);
  const [runId, setRunId] = useState("");
  const [note, setNote] = useState("");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const isRequest = kind === "requests";
  const title = isRequest ? "Requests" : "Escalations";

  async function create(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(null); setNotice(null);
    try {
      await json(await fetch(`/v1/${kind}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ run_id: runId.trim(), [isRequest ? "message" : "reason"]: note.trim() }) }));
      setRunId(""); setNote(""); setNotice(`${isRequest ? "Request" : "Escalation"} opened.`); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The item could not be opened."); }
    finally { setSaving(false); }
  }

  async function resolve(id: string) {
    const value = answers[id]?.trim();
    if (!value) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      await json(await fetch(`/v1/${kind}/${id}/resolve`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ [isRequest ? "response" : "resolution"]: value }) }));
      setNotice(`${isRequest ? "Request" : "Escalation"} resolved.`); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The item could not be resolved."); }
    finally { setSaving(false); }
  }

  return <section className="clinic-page" aria-busy={busy}>
    <header className="clinic-page-heading"><div><p className="eyebrow">{isRequest ? "Missing information" : "Lead attention"}</p><h1>{title}</h1></div><button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}>Refresh</button></header>
    <p>{isRequest ? "Track information needed to complete review and record the response." : "Escalate complex findings, then record how they were resolved."}</p>
    {error ? <p role="alert" className="clinic-error">{error}</p> : null}{notice ? <p role="status" className="clinic-success">{notice}</p> : null}
    <form className="clinic-form" onSubmit={(event) => void create(event)}><h2>Open {isRequest ? "a request" : "an escalation"}</h2>
      <label>Run ID<input required value={runId} onChange={(event) => setRunId(event.target.value)} placeholder="RUN-…" /></label>
      <label>{isRequest ? "Information needed" : "Reason"}<input required value={note} onChange={(event) => setNote(event.target.value)} /></label>
      <button type="submit" className="primary-button" disabled={saving}>Open {isRequest ? "request" : "escalation"}</button>
    </form>
    {busy ? <p>Loading {title.toLowerCase()}…</p> : null}
    {!busy && data?.length === 0 ? <p className="clinic-empty">No {title.toLowerCase()} yet.</p> : null}
    <div className="clinic-cards">{data?.map((item) => {
      const id = isRequest ? item.request_id : item.escalation_id;
      return <article className="clinic-work-card" key={id}><div><span className="status-chip">{item.status}</span><small>{new Date(item.created_at).toLocaleString()}</small></div>
        <h2>{item.run_id}</h2><p>{item.message ?? item.reason}</p>
        {item.status === "resolved" ? <p className="clinic-resolution">Resolution: {item.response ?? item.resolution}</p> : <div className="clinic-resolve"><label>Resolution<input value={answers[id ?? ""] ?? ""} onChange={(event) => setAnswers((old) => ({ ...old, [id ?? ""]: event.target.value }))} /></label><button type="button" className="secondary-button" disabled={saving || !answers[id ?? ""]?.trim()} onClick={() => void resolve(id ?? "")}>Resolve</button></div>}
      </article>;
    })}</div>
  </section>;
}

type IntakeJob = { job_id: string; filename: string; status: string; error_code: string | null; draft?: Row; run_id: string | null; created_at: string };

export function DocumentIntakePage() {
  const { data, busy, error, setError, load } = useRemote<IntakeJob[]>("/v1/intake-jobs");
  const [filename, setFilename] = useState("");
  const [content, setContent] = useState("");
  const [selected, setSelected] = useState<IntakeJob | null>(null);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  async function readFile(file: File | undefined) {
    if (!file) return;
    setFilename(file.name);
    setContent(await file.text());
  }

  async function ingest(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError(null); setNotice(null);
    try {
      const job = await json<IntakeJob>(await fetch("/v1/intake-jobs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ filename, content }) }));
      setNotice(job.status === "rejected" ? `Document rejected: ${job.error_code}.` : "Draft extracted. Review it before submitting a claim.");
      setFilename(""); setContent(""); await load();
      if (job.status === "needs_review") await inspect(job.job_id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Document intake failed."); }
    finally { setSaving(false); }
  }

  async function inspect(id: string) {
    try { setSelected(await json<IntakeJob>(await fetch(`/v1/intake-jobs/${id}`, { cache: "no-store" }))); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Draft could not be loaded."); }
  }

  async function submit() {
    if (!selected) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      const result = await json<{ run: { run_id: string } }>(await fetch(`/v1/intake-jobs/${selected.job_id}/submit`, { method: "POST" }));
      setNotice(`Claim checked and recorded as ${result.run.run_id}.`); setSelected(null); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "The draft could not be checked. Confirm the full claim envelope is present."); }
    finally { setSaving(false); }
  }

  return <section className="clinic-page" aria-busy={busy}>
    <header className="clinic-page-heading"><div><p className="eyebrow">Source to checked claim</p><h1>Document Intake</h1></div><button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}>Refresh</button></header>
    <p>The pilot accepts a ClaimGuard JSON document (up to 64 KiB). It extracts a draft, keeps the source hash, and requires human review before the same deterministic claim checks run. PDFs and free-text extraction are not yet supported.</p>
    {error ? <p role="alert" className="clinic-error">{error}</p> : null}{notice ? <p role="status" className="clinic-success">{notice}</p> : null}
    <form className="clinic-form clinic-form-wide" onSubmit={(event) => void ingest(event)}><h2>Intake a source document</h2>
      <label>JSON file<input required type="file" accept=".json,application/json" onChange={(event) => void readFile(event.target.files?.[0])} /></label>
      <button type="submit" className="primary-button" disabled={saving || !content}>Extract draft</button>
    </form>
    <h2>Recent jobs</h2>
    {busy ? <p>Loading intake jobs…</p> : null}
    {!busy && data?.length === 0 ? <p className="clinic-empty">No source documents have been processed yet.</p> : null}
    <div className="clinic-cards">{data?.map((job) => <article className="clinic-work-card" key={job.job_id}><div><span className="status-chip">{job.status}</span><small>{new Date(job.created_at).toLocaleString()}</small></div><h2>{job.filename}</h2><p>{job.error_code ? `Issue: ${job.error_code}` : job.run_id ? `Checked run: ${job.run_id}` : "Draft ready for review"}</p>{job.status === "needs_review" ? <button type="button" className="secondary-button" onClick={() => void inspect(job.job_id)}>Review draft</button> : null}</article>)}</div>
    {selected ? <div className="drawer-backdrop"><section className="correction-drawer" aria-label="Intake draft"><header><h2>Review extracted draft</h2><button type="button" className="secondary-button" onClick={() => setSelected(null)}>Close</button></header><p>Verify all fields against the original source. Submitting runs the deterministic engine; it does not approve a claim.</p><pre className="clinic-json-preview">{JSON.stringify(selected.draft, null, 2)}</pre><div className="drawer-actions"><button type="button" className="primary-button" disabled={saving} onClick={() => void submit()}>Check and create claim</button></div></section></div> : null}
  </section>;
}

export function ConfigurationPage() {
  const { data, busy, error, setError, load } = useRemote<{ intake_enabled: boolean }>("/v1/configuration");
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  async function toggle() {
    if (!data) return;
    setSaving(true); setError(null); setNotice(null);
    try {
      const changed = await json<{ intake_enabled: boolean }>(await fetch("/v1/configuration", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ intake_enabled: !data.intake_enabled }) }));
      setNotice(`Document intake ${changed.intake_enabled ? "enabled" : "disabled"}.`); await load();
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Configuration could not be changed."); }
    finally { setSaving(false); }
  }
  return <section className="clinic-page" aria-busy={busy}><header className="clinic-page-heading"><div><p className="eyebrow">Clinic service controls</p><h1>Configuration</h1></div><button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}>Refresh</button></header><p>Only operational settings are exposed here. This role cannot read claims.</p>{error ? <p role="alert" className="clinic-error">{error}</p> : null}{notice ? <p role="status" className="clinic-success">{notice}</p> : null}{data ? <div className="clinic-config-card"><div><h2>Document intake</h2><p>{data.intake_enabled ? "Enabled" : "Disabled"} for this clinic</p></div><button type="button" className="secondary-button" disabled={saving} onClick={() => void toggle()}>{data.intake_enabled ? "Disable" : "Enable"} intake</button></div> : null}</section>;
}

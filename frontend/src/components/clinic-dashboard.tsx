"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, ClipboardList, FileClock, FolderInput, RefreshCw, Users, ShieldCheck } from "lucide-react";
import { Button } from "./ui/button";

type Overview = { claims: number; assigned_claims: number; open_requests: number; open_escalations: number; intake_pending: number };
type Analytics = { overview: Overview; daily: { day: string; runs: number; claims: number }[]; findings_by_status: { status: string; total: number }[] };
const STATUS_LABELS: Record<string, string> = { PASS: "Passed", FAIL: "Issues found", UNABLE_TO_ASSESS: "More evidence needed", NOT_APPLICABLE: "Not applicable", NOT_IMPLEMENTED: "Not implemented" };

export function ClinicDashboard({ analytics = false }: { analytics?: boolean }) {
  const [data, setData] = useState<Analytics | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      const response = await fetch("/v1/analytics", { cache: "no-store" });
      if (!response.ok) throw new Error("Clinic reporting could not be loaded. Please refresh to try again.");
      setData(await response.json() as Analytics);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Reporting is unavailable."); }
    finally { setBusy(false); }
  }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 0); return () => window.clearTimeout(timer); }, [load]);
  const overview = data?.overview;
  const days = [...(data?.daily ?? [])].reverse();
  const maximum = Math.max(1, ...days.map((day) => day.runs));
  const total = data?.findings_by_status.reduce((sum, row) => sum + row.total, 0) ?? 0;
  const cards = overview ? [
    { label: "Claims in your clinic", value: overview.claims, detail: "All recorded claims", icon: ClipboardList, href: "all-claims", tone: "blue" },
    { label: "Awaiting assignment", value: Math.max(0, overview.claims - overview.assigned_claims), detail: `${overview.assigned_claims} claims assigned`, icon: Users, href: "assignments", tone: "aqua" },
    { label: "Open requests", value: overview.open_requests, detail: "Managed in your RCM team's Requests page", icon: FileClock, href: null, tone: "amber" },
    { label: "Intake awaiting review", value: overview.intake_pending, detail: "Drafts in your RCM team's Document Intake", icon: FolderInput, href: null, tone: "navy" },
  ] : [];
  return <section className="clinic-page dashboard-page" aria-busy={busy}>
    <header className="clinic-page-heading"><div><p className="eyebrow">Your clinic at a glance</p><h1>{analytics ? "Clinic analytics" : "A clearer view of your clinic."}</h1><p className="page-subtitle">{analytics ? "Track recorded checks and review volume across your clinic." : "See what needs attention. Keep your team moving."}</p></div><div className="page-actions"><Button variant="outline" onClick={() => void load()} disabled={busy}><RefreshCw size={16} className={busy ? "refreshing" : ""} /> Refresh</Button><Link className="primary-button" href="/workspace/all-claims">View claims <ArrowRight size={16} /></Link></div></header>
    {error ? <div className="clinic-error" role="alert">{error}</div> : null}
    {busy && !data ? <div className="dashboard-skeleton" role="status" aria-label="Loading clinic overview"><div /><div /><div /><div /></div> : null}
    {overview ? <>
      <div className="dashboard-stats">{cards.map(({ icon: Icon, ...card }) => {
        const content = <><div><span className="stat-icon"><Icon size={19} /></span><span>{card.label}</span>{card.href ? <ArrowRight size={14} /> : null}</div><strong>{card.value.toLocaleString()}</strong><p>{card.detail}</p></>;
        return card.href ? <Link href={`/workspace/${card.href}`} key={card.label} className={`dashboard-stat ${card.tone}`}>{content}</Link> : <div key={card.label} className={`dashboard-stat ${card.tone}`}>{content}</div>;
      })}</div>
      <div className="dashboard-grid"><section className="dashboard-panel volume-panel"><header><div><p className="eyebrow">Work arriving</p><h2>Claim check activity</h2></div><span className="subtle-label">Latest {days.length} active days</span></header>
        {days.length ? <><div className="volume-chart" aria-label="Check runs per active day">{days.map((day) => <div className="volume-column" key={day.day}><span>{day.runs}</span><div className="volume-track"><div style={{ height: `${Math.max(2, day.runs / maximum * 100)}%` }} title={`${day.day}: ${day.runs} check runs, ${day.claims} distinct claims`} /></div><time dateTime={day.day}>{new Date(`${day.day}T12:00:00`).toLocaleDateString("en", { month: "short", day: "numeric" })}</time></div>)}</div><p className="chart-caption">Check runs include rechecks. Each correction is recorded as a new version.</p><details className="chart-data"><summary>View exact activity data</summary><table className="clinic-table"><thead><tr><th>Date</th><th>Check runs</th><th>Distinct claims</th></tr></thead><tbody>{days.map((day) => <tr key={day.day}><td>{day.day}</td><td>{day.runs}</td><td>{day.claims}</td></tr>)}</tbody></table></details></> : <p className="clinic-empty">Activity will appear after your first claim is checked.</p>}
      </section><section className="dashboard-panel"><header><div><p className="eyebrow">Evidence, at a glance</p><h2>Check outcomes</h2></div><ShieldCheck size={20} /></header><p className="outcome-total"><strong>{total.toLocaleString()}</strong> recorded rule results</p><div className="outcome-list">{data?.findings_by_status.map((row) => <div key={row.status}><div><span className={`outcome-dot ${row.status.toLowerCase()}`} /><span>{STATUS_LABELS[row.status] ?? row.status}</span><strong>{row.total.toLocaleString()}</strong></div><meter min={0} max={Math.max(1, total)} value={row.total} aria-label={`${STATUS_LABELS[row.status] ?? row.status} results`} /></div>)}</div>{total === 0 ? <p className="chart-caption">No checks recorded yet.</p> : <p className="chart-caption">Rule results across all versions. A passed check is not payer approval.</p>}</section></div>
      {!analytics ? <div className="dashboard-grid dashboard-bottom"><section className="dashboard-panel"><header><div><p className="eyebrow">Keep the work moving</p><h2>Next priorities</h2></div></header><Link className="priority-row" href="/workspace/assignments"><span className="priority-icon"><Users size={20} /></span><span><strong>Give every claim an owner</strong><small>{Math.max(0, overview.claims - overview.assigned_claims)} claims awaiting assignment</small></span><ArrowRight size={18} /></Link><Link className="priority-row" href="/workspace/all-claims"><span className="priority-icon"><FileClock size={20} /></span><span><strong>Follow up on outstanding review</strong><small>{overview.open_requests} open requests · {overview.open_escalations} open escalations</small></span><ArrowRight size={18} /></Link></section><section className="dashboard-panel team-panel"><p className="eyebrow">An organized clinic</p><h2>The right people.<br />The right access.</h2><p>Manage your departments and review team from one place.</p><div><Link href="/workspace/team-access">Manage team <ArrowRight size={16} /></Link><Link href="/workspace/departments">Departments <ArrowRight size={16} /></Link></div></section></div> : null}
    </> : null}
  </section>;
}

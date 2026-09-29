"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Database,
  Gauge,
  LayoutDashboard,
  RefreshCw,
  Server,
  ShieldAlert,
  Timer,
  XCircle,
} from "lucide-react";
import {
  getOpsOverview,
  getOpsMetrics,
  getOpsTraces,
  getOpsAudit,
  type OpsTrace,
  type OpsWindow,
  type OpsOverviewResponse,
  type OpsMetricsResponse,
  type OpsTracesResponse,
  type OpsAuditResponse,
} from "@/lib/ops-api";

const REFRESH_INTERVAL_MS = 30_000;

type Loadable<T> = { state: "loading" } | { state: "ok"; data: T } | { state: "error"; message: string };
type OpsSnapshot = { overview: OpsOverviewResponse; metrics: OpsMetricsResponse; traces: OpsTracesResponse; audit: OpsAuditResponse };

const fetchSnapshot = async (window: OpsWindow, signal?: AbortSignal): Promise<OpsSnapshot> => {
  const [overview, metrics, traces, audit] = await Promise.all([
    getOpsOverview(signal),
    getOpsMetrics(window, signal),
    getOpsTraces(25, signal),
    getOpsAudit(signal),
  ]);
  return { overview, metrics, traces, audit };
};

const fetchErrorMessage = (err: unknown): string =>
  err instanceof Error ? err.message : "Could not reach the operations backend.";

const fmtTime = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};

const fmtRel = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 0) return fmtTime(iso);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
};

const tone = (state: string) => {
  if (state === "healthy") return "success";
  if (state === "degraded" || state === "stale") return "warning";
  if (state === "unavailable" || state === "unknown") return "danger";
  return "neutral";
};

const StateBadge = ({ state }: { state: string }) => <span className={`ops-state ops-state-${tone(state)}`}>{state}</span>;

const Skeleton = () => (
  <div className="ops-skeleton">
    <div className="ops-skeleton-line" style={{ width: "60%" }} />
    <div className="ops-skeleton-line" style={{ width: "85%" }} />
    <div className="ops-skeleton-line" style={{ width: "70%" }} />
  </div>
);

const Labels = ({ labels }: { labels: Readonly<Record<string, string>> }) => {
  const entries = Object.entries(labels);
  if (entries.length === 0) return <span className="ops-quiet">none</span>;
  return <div className="ops-labels">{entries.map(([k, v]) => <span key={k} className="ops-label">{k}={v}</span>)}</div>;
};

function WindowSwitch({ value, onChange }: { value: OpsWindow; onChange: (w: OpsWindow) => void }) {
  return (
    <fieldset className="ops-window-switch">
      <legend className="ops-sr-only">Metrics window</legend>
      {(["5m", "15m", "1h"] as OpsWindow[]).map((w) => (
        <button key={w} type="button" className={w === value ? "ops-active" : ""} onClick={() => onChange(w)} aria-pressed={w === value}>{w}</button>
      ))}
    </fieldset>
  );
}

export function OpsConsole() {
  const [window, setWindow] = useState<OpsWindow>("5m");
  const [snap, setSnap] = useState<Loadable<OpsSnapshot>>({ state: "loading" });
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async (signal?: AbortSignal) => {
    setBusy(true);
    try {
      setSnap({ state: "ok", data: await fetchSnapshot(window, signal) });
    } catch (err) {
      setSnap({ state: "error", message: fetchErrorMessage(err) });
    } finally {
      setBusy(false);
    }
  }, [window]);

  useEffect(() => {
    const c = new AbortController();
    const tick = async () => {
      try {
        const data = await fetchSnapshot(window, c.signal);
        if (c.signal.aborted) return;
        setSnap({ state: "ok", data });
      } catch (err) {
        if (c.signal.aborted) return;
        setSnap({ state: "error", message: fetchErrorMessage(err) });
      }
    };
    void tick();
    const id = setInterval(() => { void tick(); }, REFRESH_INTERVAL_MS);
    return () => { c.abort(); clearInterval(id); };
  }, [window]);

  const status = snap.state === "ok" ? snap.data.overview.status : "unknown";
  const checkedAt = snap.state === "ok" ? snap.data.overview.checked_at : null;

  return (
    <main className="ops-console" aria-label="Operations console">
      <header className="ops-header">
        <div className="ops-header-main">
          <div className="ops-title">
            <LayoutDashboard size={22} aria-hidden="true" />
            <div>
              <h1>Operations Console</h1>
              <p className="ops-subtitle">Technical reviewer operations overview</p>
            </div>
          </div>
          <div className={`ops-verdict ops-verdict-${status}`} aria-live="polite" aria-atomic="true">
            {status === "ok" && <CheckCircle2 size={18} aria-hidden="true" />}
            {status === "degraded" && <AlertTriangle size={18} aria-hidden="true" />}
            {status === "unknown" && <Activity size={18} aria-hidden="true" />}
            <span>Platform {status}</span>
          </div>
        </div>
        <div className="ops-header-meta">
          <span className="ops-checked-at"><Clock size={13} aria-hidden="true" />Checked {fmtRel(checkedAt)}</span>
          <button type="button" className="ops-refresh-button" onClick={() => refresh()} disabled={busy} aria-label="Refresh operations data">
            <RefreshCw size={15} className={busy ? "ops-spin" : ""} aria-hidden="true" />Refresh
          </button>
        </div>
      </header>

      {snap.state === "error" && (
        <div className="ops-error-card">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{snap.message}</span>
          <button type="button" onClick={() => refresh()}>Retry</button>
        </div>
      )}

      {snap.state === "loading" && (
        <div className="ops-layout">
          <section className="ops-panel" aria-label="Components"><h2 className="ops-panel-title">Components</h2><Skeleton /></section>
          <section className="ops-panel" aria-label="Sources"><h2 className="ops-panel-title">Source freshness</h2><Skeleton /></section>
          <section className="ops-panel" aria-label="Metrics"><div className="ops-panel-header"><h2 className="ops-panel-title">Metrics</h2><WindowSwitch value={window} onChange={setWindow} /></div><Skeleton /></section>
          <section className="ops-panel" aria-label="Traces"><h2 className="ops-panel-title">Traces</h2><Skeleton /></section>
          <section className="ops-panel" aria-label="Audit integrity"><h2 className="ops-panel-title">Audit integrity</h2><Skeleton /></section>
        </div>
      )}

      {snap.state === "ok" && (
        <div className="ops-layout">
          <section className="ops-panel" aria-label="Components">
            <h2 className="ops-panel-title">Components</h2>
            <div className="ops-card-grid">
              {snap.data.overview.components.map((c) => (
                <div key={c.name} className={`ops-card ops-card-${tone(c.state)}`}>
                  <div className="ops-card-top">{c.name.toLowerCase().includes("database") ? <Database size={18} aria-hidden="true" /> : <Server size={18} aria-hidden="true" />}<StateBadge state={c.state} /></div>
                  <div className="ops-card-body"><strong>{c.name}</strong><p>{c.detail ?? "No detail provided."}</p></div>
                </div>
              ))}
              {snap.data.overview.components.length === 0 && <p className="ops-empty">No components reported.</p>}
            </div>
          </section>

          <section className="ops-panel" aria-label="Sources">
            <h2 className="ops-panel-title">Source freshness</h2>
            <div className="ops-card-grid">
              {snap.data.overview.sources.map((s) => (
                <div key={s.name} className={`ops-card ops-card-${tone(s.state)} ${s.state === "stale" ? "ops-card-stale" : ""} ${s.state === "unavailable" ? "ops-card-unavailable" : ""}`}>
                  <div className="ops-card-top"><Gauge size={18} aria-hidden="true" /><StateBadge state={s.state} /></div>
                  <div className="ops-card-body">
                    <strong>{s.name}</strong>
                    <p>{s.detail ?? "No detail provided."}</p>
                    <div className="ops-source-meta"><span><Clock size={12} aria-hidden="true" />Last data: {fmtRel(s.last_data_at)} ({fmtTime(s.last_data_at)})</span></div>
                  </div>
                </div>
              ))}
              {snap.data.overview.sources.length === 0 && <p className="ops-empty">No sources reported.</p>}
            </div>
          </section>

          <section className="ops-panel" aria-label="Metrics">
            <div className="ops-panel-header"><h2 className="ops-panel-title">Metrics</h2><WindowSwitch value={window} onChange={setWindow} /></div>
            {snap.data.metrics.series.length === 0 ? (
              <div className="ops-empty-state"><Activity size={24} aria-hidden="true" /><p>No metrics available for this window.</p><small>Source state: {snap.data.metrics.source.state}</small></div>
            ) : (
              <div className="ops-table-wrap">
                <table className="ops-table">
                  <thead><tr><th scope="col">Metric</th><th scope="col">Labels</th><th scope="col" className="ops-numeric">Value</th></tr></thead>
                  <tbody>
                    {snap.data.metrics.series.map((s) => {
                      const labelKey = Object.entries(s.labels).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k}=${v}`).join("|");
                      return (
                        <tr key={`${s.name}::${labelKey}`}>
                          <td className="ops-metric-name">{s.name}</td>
                          <td><Labels labels={s.labels} /></td>
                          <td className="ops-numeric ops-metric-value">{s.value.toLocaleString()}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="ops-panel" aria-label="Traces">
            <h2 className="ops-panel-title">Traces</h2>
            <Traces traces={snap.data.traces.traces} />
          </section>

          <section className={`ops-audit-banner ${snap.data.audit.intact ? "ops-audit-ok" : "ops-audit-broken"}`} aria-label="Audit integrity">
            <div className="ops-audit-icon">{snap.data.audit.intact ? <ShieldAlert size={22} aria-hidden="true" /> : <XCircle size={22} aria-hidden="true" />}</div>
            <div className="ops-audit-body">
              <h2>{snap.data.audit.intact ? "Audit chain intact" : "Audit chain integrity failure"}</h2>
              <p>{snap.data.audit.intact ? `Hash-chained audit ledger verified. ${snap.data.audit.event_count.toLocaleString()} events.` : "Audit ledger integrity check failed. Escalate immediately."}</p>
              <span className="ops-checked-at">Checked {fmtRel(snap.data.audit.checked_at)}</span>
            </div>
          </section>

          <section className="ops-version-strip" aria-label="Version information">
            <span><strong>Rule engine</strong> {snap.data.overview.versions.engine_rule_version}</span>
            <span><strong>Schema</strong> {snap.data.overview.versions.schema_revision ?? "—"}</span>
            <span><strong>Service</strong> {snap.data.overview.versions.service_name}</span>
          </section>
        </div>
      )}
    </main>
  );
}

function Traces({ traces }: { traces: readonly OpsTrace[] }) {
  const max = useMemo(() => Math.max(1, ...traces.map((t) => t.duration_ms)), [traces]);
  if (traces.length === 0) return <div className="ops-empty-state"><Timer size={24} aria-hidden="true" /><p>No recent traces.</p></div>;
  return (
    <div className="ops-table-wrap">
      <table className="ops-table">
        <thead><tr><th scope="col">Root operation</th><th scope="col">Service</th><th scope="col">Started</th><th scope="col">Duration</th></tr></thead>
        <tbody>
          {traces.map((t) => (
            <tr key={t.trace_id}>
              <td className="ops-trace-name"><code title={t.trace_id}>{t.root_name}</code></td>
              <td>{t.service}</td>
              <td>{fmtRel(t.start_time)}</td>
              <td>
                <div className="ops-duration">
                  <span className="ops-duration-bar"><span className="ops-duration-fill" style={{ width: `${(t.duration_ms / max) * 100}%` }} /></span>
                  <span className="ops-duration-value">{t.duration_ms.toLocaleString()} ms</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

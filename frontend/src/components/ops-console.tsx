"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import {
  Activity,
  AlertTriangle,
  Clock,
  LayoutDashboard,
  RefreshCw,
  Timer,
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
  type OpsMetricSeries,
  type OpsTracesResponse,
  type OpsAuditResponse,
} from "@/lib/ops-api";

const REFRESH_INTERVAL_MS = 30_000;
const STAGGER_MS = 35;
const MAX_STAGGER_NODES = 8;
const HASH_LINK_IDS = ["h0", "h1", "h2", "h3", "h4", "h5", "h6", "h7", "h8", "h9", "h10", "h11"];

type Loadable<T> =
  | { state: "loading" }
  | { state: "ok"; data: T }
  | { state: "error"; message: string };
type OpsSnapshot = {
  overview: OpsOverviewResponse;
  metrics: OpsMetricsResponse | null;
  traces: OpsTracesResponse | null;
  audit: OpsAuditResponse | null;
};

const fetchSnapshot = async (
  window: OpsWindow,
  section: OpsConsoleProps["section"],
  signal?: AbortSignal,
): Promise<OpsSnapshot> => {
  if (section === "overview") {
    const overview = await getOpsOverview(signal);
    return { overview, metrics: null, traces: null, audit: null };
  }
  if (section === "metrics") {
    const [overview, metrics] = await Promise.all([
      getOpsOverview(signal),
      getOpsMetrics(window, signal),
    ]);
    return { overview, metrics, traces: null, audit: null };
  }
  if (section === "traces") {
    const [overview, traces] = await Promise.all([
      getOpsOverview(signal),
      getOpsTraces(25, signal),
    ]);
    return { overview, metrics: null, traces, audit: null };
  }
  if (section === "audit") {
    const [overview, audit] = await Promise.all([
      getOpsOverview(signal),
      getOpsAudit(signal),
    ]);
    return { overview, metrics: null, traces: null, audit };
  }
  const [overview, metrics, traces, audit] = await Promise.all([
    getOpsOverview(signal),
    getOpsMetrics(window, signal),
    getOpsTraces(25, signal),
    getOpsAudit(signal),
  ]);
  return { overview, metrics, traces, audit };
};

const fetchErrorMessage = (err: unknown): string =>
  err instanceof Error
    ? err.message
    : "Could not reach the operations backend.";

const fmtTime = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
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

type Tone = "success" | "warning" | "danger" | "neutral";

const tone = (state: string): Tone => {
  if (state === "healthy") return "success";
  if (state === "degraded" || state === "stale") return "warning";
  if (state === "unavailable" || state === "unknown") return "danger";
  return "neutral";
};

const StateBadge = ({ state }: { state: string }) => (
  <span className={`ops-state ops-state-${tone(state)}`}>{state}</span>
);

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
  return (
    <div className="ops-labels">
      {entries.map(([k, v]) => (
        <span key={k} className="ops-label">
          {k}={v}
        </span>
      ))}
    </div>
  );
};

function WindowSwitch({
  value,
  onChange,
}: {
  value: OpsWindow;
  onChange: (w: OpsWindow) => void;
}) {
  return (
    <fieldset className="ops-window-switch">
      <legend className="ops-sr-only">Metrics window</legend>
      {(["5m", "15m", "1h"] as OpsWindow[]).map((w) => (
        <button
          key={w}
          type="button"
          className={w === value ? "ops-active" : ""}
          onClick={() => onChange(w)}
          aria-pressed={w === value}
        >
          {w}
        </button>
      ))}
    </fieldset>
  );
}

function metricHeatLevel(value: number, max: number): 1 | 2 | 3 | 4 | 5 {
  if (max <= 0 || value <= 0) return 1;
  const ratio = value / max;
  if (ratio < 0.2) return 1;
  if (ratio < 0.4) return 2;
  if (ratio < 0.6) return 3;
  if (ratio < 0.8) return 4;
  return 5;
}

function traceLatencyClass(ms: number): "fast" | "medium" | "slow" {
  if (ms < 100) return "fast";
  if (ms < 500) return "medium";
  return "slow";
}

type OpsConsoleProps = {
  variant?: "page" | "embedded";
  section?: "overview" | "metrics" | "traces" | "audit";
};

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

function usePrefersReducedMotion() {
  return useSyncExternalStore(
    (callback) => {
      if (typeof window === "undefined" || !window.matchMedia) return () => {};
      const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
      mql.addEventListener("change", callback);
      return () => mql.removeEventListener("change", callback);
    },
    () => {
      if (typeof window === "undefined" || !window.matchMedia) return false;
      return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    },
    () => false,
  );
}

function SignalRail({ alive, pulseKey }: { alive: boolean; pulseKey: number }) {
  return (
    <div className={`ops-signal-rail ${alive ? "ops-signal-rail-alive" : "ops-signal-rail-dead"}`} aria-hidden="true">
      <svg preserveAspectRatio="none" viewBox="0 0 1200 24" aria-hidden="true">
        <polyline
          key={alive ? pulseKey : "static"}
          className="ops-signal-polyline"
          points="0,20 120,4 260,18 420,8 580,16 760,6 920,14 1080,10 1200,20"
          fill="none"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

function VerdictGauge({ status }: { status: string }) {
  const reduced = usePrefersReducedMotion();
  const ok = status === "ok";
  const degraded = status === "degraded";
  const toneClass = ok ? "ops-gauge-ok" : degraded ? "ops-gauge-degraded" : "ops-gauge-unknown";
  const label = `Platform ${status}`;
  return (
    <div className={`ops-verdict-gauge ${toneClass}`} aria-live="polite" aria-atomic="true">
      <svg viewBox="0 0 40 40" aria-hidden="true" className="ops-gauge-face">
        <circle className="ops-gauge-track" cx="20" cy="20" r="15" />
        <circle className={`ops-gauge-arc ${reduced ? "" : "ops-gauge-arc-sweep"}`} cx="20" cy="20" r="15" />
      </svg>
      <span className="ops-verdict-label">{label}</span>
    </div>
  );
}

type SignalMapNode = {
  name: string;
  state: string;
  detail: string | null;
  last_data_at?: string | null;
  kind: "platform" | "component" | "source";
};

function SignalMap({
  components,
  sources,
  pulseKey,
}: {
  components: readonly { name: string; state: string; detail: string | null }[];
  sources: readonly { name: string; state: string; detail: string | null; last_data_at: string | null }[];
  pulseKey: number;
}) {
  const reduced = usePrefersReducedMotion();

  return (
    <div className="ops-signal-map">
      <div className="ops-signal-map-platform">
        <div className="ops-signal-node ops-signal-node-platform" aria-hidden="true">
          <span className="ops-signal-node-dot" />
          <span className="ops-signal-node-name">platform</span>
        </div>
      </div>

      <section className="ops-signal-map-region" aria-label="Components">
        <h2 className="ops-panel-title">Components</h2>
        <div className="ops-signal-map-nodes">
          {components.map((c, i) => (
            <SignalNode
              key={c.name}
              node={{ ...c, kind: "component" }}
              index={i}
              edgeState={c.state}
              reduced={reduced}
              pulseKey={pulseKey}
            />
          ))}
          {components.length === 0 && <p className="ops-empty">No components reported.</p>}
        </div>
      </section>

      <section className="ops-signal-map-region" aria-label="Sources">
        <h2 className="ops-panel-title">Source freshness</h2>
        <div className="ops-signal-map-nodes">
          {sources.map((s, i) => (
            <SignalNode
              key={s.name}
              node={{ ...s, kind: "source" }}
              index={i + components.length}
              edgeState={s.state}
              reduced={reduced}
              pulseKey={pulseKey}
            />
          ))}
          {sources.length === 0 && <p className="ops-empty">No sources reported.</p>}
        </div>
      </section>
    </div>
  );
}

function SignalNode({
  node,
  index,
  edgeState,
  reduced,
  pulseKey,
}: {
  node: SignalMapNode;
  index: number;
  edgeState: string;
  reduced: boolean;
  pulseKey: number;
}) {
  const t = tone(node.state);
  const stale = edgeState === "stale";
  const unavailable = edgeState === "unavailable";
  const [pulse, setPulse] = useState(0);
  const lastPulseRef = useRef(pulseKey);
  const style = {
    transitionDelay: reduced ? "0ms" : `${clamp(index, 0, MAX_STAGGER_NODES - 1) * STAGGER_MS}ms`,
  };

  useEffect(() => {
    if (pulseKey !== lastPulseRef.current) {
      lastPulseRef.current = pulseKey;
      setPulse((p) => p + 1);
    }
  }, [pulseKey]);

  return (
    <div
      className={`ops-signal-node ops-signal-node-${t} ${stale ? "ops-signal-node-stale" : ""} ${unavailable ? "ops-signal-node-unavailable" : ""} ${reduced ? "" : "ops-signal-node-enter"}`}
      style={style}
    >
      <div className="ops-signal-node-top">
        <div className="ops-signal-edge" aria-hidden="true">
          <svg viewBox="0 0 40 40" preserveAspectRatio="none" aria-hidden="true" key={pulse} className={reduced ? "" : "ops-signal-edge-pulse"}>
            <line
              className={`ops-signal-edge-line ${stale ? "ops-edge-stale" : ""} ${unavailable ? "ops-edge-broken" : ""}`}
              x1="0"
              y1="0"
              x2="40"
              y2="40"
            />
          </svg>
        </div>
        <span className="ops-signal-node-name">{node.name}</span>
        <StateBadge state={node.state} />
      </div>
      <p className="ops-signal-node-detail">{node.detail ?? "No detail provided."}</p>
      {node.kind === "source" && (
        <div className="ops-signal-node-freshness">
          <Clock size={12} aria-hidden="true" />
          <span>Last data: {fmtRel(node.last_data_at ?? null)} ({fmtTime(node.last_data_at ?? null)})</span>
        </div>
      )}
    </div>
  );
}

function HashChain({ intact, eventCount, checkedAt }: { intact: boolean; eventCount: number; checkedAt: string }) {
  const reduced = usePrefersReducedMotion();
  const displayed = eventCount > 0 ? clamp(Math.min(eventCount, 12), 1, 12) : 0;
  const remainder = Math.max(0, eventCount - displayed);
  return (
    <section className={`ops-hash-chain ${intact ? "ops-hash-chain-intact" : "ops-hash-chain-broken"}`} aria-label="Audit integrity">
      <div className="ops-hash-chain-header">
        <h2 className="ops-panel-title">Audit integrity</h2>
        <span className="ops-hash-chain-count">{eventCount.toLocaleString()} events</span>
      </div>
      <div className="ops-hash-chain-track" aria-hidden="true">
        <div className={`ops-hash-chain-line ${intact ? "" : "ops-hash-chain-line-broken"}`} />
        <div className={`ops-hash-links ${reduced ? "" : "ops-hash-links-animate"}`}>
          {HASH_LINK_IDS.slice(0, displayed).map((id, i) => (
            <div
              key={id}
              className={`ops-hash-link ${i >= Math.floor(displayed / 2) && !intact ? "ops-hash-link-fallen" : ""}`}
              style={{
                transitionDelay: reduced ? "0ms" : `${i * 40}ms`,
              }}
            >
              <span className="ops-hash-link-face" />
            </div>
          ))}
          {remainder > 0 && <span className="ops-hash-more">+{remainder.toLocaleString()} more</span>}
        </div>
      </div>
      <div className="ops-hash-chain-body">
        <h3>{intact ? "Audit chain intact" : "Audit chain integrity failure"}</h3>
        <p>
          {intact
            ? "Hash-chained audit ledger verified. Each block links to the previous."
            : "Audit ledger integrity check failed. Escalate immediately."}
        </p>
        <span className="ops-checked-at">Checked {fmtRel(checkedAt)}</span>
      </div>
    </section>
  );
}

const SECTION_TITLES: Record<OpsConsoleProps["section"] & string, { title: string; subtitle: string }> = {
  overview: { title: "Operations", subtitle: "Technical reviewer operations overview" },
  metrics: { title: "Metrics", subtitle: "Operational metrics" },
  traces: { title: "Traces", subtitle: "Recent distributed traces" },
  audit: { title: "Audit Integrity", subtitle: "Tamper-evidence audit ledger" },
};

export function OpsConsole({ variant = "page", section }: OpsConsoleProps) {
  const [window, setWindow] = useState<OpsWindow>("5m");
  const [snap, setSnap] = useState<Loadable<OpsSnapshot>>({ state: "loading" });
  const [busy, setBusy] = useState(false);
  const [pulseKey, setPulseKey] = useState(0);
  const embedded = variant === "embedded";

  const setOk = useCallback((data: OpsSnapshot) => {
    setSnap({ state: "ok", data });
    setPulseKey((k) => k + 1);
  }, []);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      setBusy(true);
      try {
        setOk(await fetchSnapshot(window, section, signal));
      } catch (err) {
        setSnap({ state: "error", message: fetchErrorMessage(err) });
      } finally {
        setBusy(false);
      }
    },
    [window, section, setOk],
  );

  useEffect(() => {
    const c = new AbortController();
    const tick = async () => {
      try {
        const data = await fetchSnapshot(window, section, c.signal);
        if (c.signal.aborted) return;
        setOk(data);
      } catch (err) {
        if (c.signal.aborted) return;
        setSnap({ state: "error", message: fetchErrorMessage(err) });
      }
    };
    void tick();
    const id = setInterval(() => {
      void tick();
    }, REFRESH_INTERVAL_MS);
    return () => {
      c.abort();
      clearInterval(id);
    };
  }, [window, section, setOk]);

  const status = snap.state === "ok" ? snap.data.overview.status : "unknown";
  const checkedAt = snap.state === "ok" ? snap.data.overview.checked_at : null;
  const sectionMeta = section ? SECTION_TITLES[section] : { title: "Operations Console", subtitle: "Technical reviewer operations overview" };

  const showOverview = !section || section === "overview";
  const showMetrics = !section || section === "metrics";
  const showTraces = !section || section === "traces";
  const showAudit = !section || section === "audit";

  return (
    <div className={`ops-dark ${embedded ? "ops-dark-embedded" : ""}`}>
      <SignalRail alive={snap.state === "ok"} pulseKey={pulseKey} />
      <main
        className={`ops-console ${embedded ? "ops-console-embedded" : ""}`}
        aria-label="Operations console"
      >
        <header className="ops-header">
          <div className="ops-header-main">
            <div className="ops-title">
              <LayoutDashboard size={22} aria-hidden="true" />
              <div>
                <h1>{sectionMeta.title}</h1>
                <p className="ops-subtitle">{sectionMeta.subtitle}</p>
              </div>
            </div>
            <VerdictGauge status={status} />
          </div>
          <div className="ops-header-meta">
            <span className="ops-checked-at">
              <Clock size={13} aria-hidden="true" />
              Checked {fmtRel(checkedAt)}
            </span>
            <button
              type="button"
              className="ops-refresh-button"
              onClick={() => refresh()}
              disabled={busy}
              aria-label="Refresh operations data"
              title="Refresh operations data"
            >
              <RefreshCw
                size={16}
                className={busy ? "ops-spin" : ""}
                aria-hidden="true"
              />
            </button>
          </div>
        </header>

        {snap.state === "error" && (
          <div className="ops-error-card">
            <AlertTriangle size={18} aria-hidden="true" />
            <span>{snap.message}</span>
            <button type="button" onClick={() => refresh()}>
              Retry
            </button>
          </div>
        )}

        {snap.state === "loading" && (
          <div className="ops-layout">
            {showOverview && (
              <>
                <section className="ops-panel" aria-label="Components">
                  <h2 className="ops-panel-title">Components</h2>
                  <Skeleton />
                </section>
                <section className="ops-panel" aria-label="Sources">
                  <h2 className="ops-panel-title">Source freshness</h2>
                  <Skeleton />
                </section>
              </>
            )}
            {showMetrics && (
              <section className="ops-panel" aria-label="Metrics">
                <div className="ops-panel-header">
                  <h2 className="ops-panel-title">Metrics</h2>
                  <WindowSwitch value={window} onChange={setWindow} />
                </div>
                <Skeleton />
              </section>
            )}
            {showTraces && (
              <section className="ops-panel" aria-label="Traces">
                <h2 className="ops-panel-title">Traces</h2>
                <Skeleton />
              </section>
            )}
            {showAudit && (
              <section className="ops-panel" aria-label="Audit integrity">
                <h2 className="ops-panel-title">Audit integrity</h2>
                <Skeleton />
              </section>
            )}
          </div>
        )}

        {snap.state === "ok" && (
          <div className="ops-layout">
            {showOverview && (
              <>
                <SignalMap
                  components={snap.data.overview.components}
                  sources={snap.data.overview.sources}
                  pulseKey={pulseKey}
                />

                <section
                  className="ops-version-strip"
                  aria-label="Version information"
                >
                  <span>
                    <strong>Rule engine</strong>{" "}
                    {snap.data.overview.versions.engine_rule_version}
                  </span>
                  <span>
                    <strong>Schema</strong>{" "}
                    {snap.data.overview.versions.schema_revision ?? "—"}
                  </span>
                  <span>
                    <strong>Service</strong>{" "}
                    {snap.data.overview.versions.service_name}
                  </span>
                </section>
              </>
            )}

            {showMetrics && snap.data.metrics && (
              <section className="ops-panel" aria-label="Metrics">
                <div className="ops-panel-header">
                  <h2 className="ops-panel-title">Metrics</h2>
                  <WindowSwitch value={window} onChange={setWindow} />
                </div>
                {snap.data.metrics.series.length === 0 ? (
                  <div className="ops-empty-state">
                    <Activity size={24} aria-hidden="true" />
                    <p>No metrics available for this window.</p>
                    <small>Source state: {snap.data.metrics.source.state}</small>
                  </div>
                ) : (
                  <MetricsTable series={snap.data.metrics.series} />
                )}
              </section>
            )}

            {showTraces && snap.data.traces && (
              <section className="ops-panel" aria-label="Traces">
                <h2 className="ops-panel-title">Traces</h2>
                <Traces traces={snap.data.traces.traces} />
              </section>
            )}

            {showAudit && snap.data.audit && (
              <HashChain
                intact={snap.data.audit.intact}
                eventCount={snap.data.audit.event_count}
                checkedAt={snap.data.audit.checked_at}
              />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function MetricsTable({ series }: { series: readonly OpsMetricSeries[] }) {
  const reduced = usePrefersReducedMotion();
  const max = useMemo(() => Math.max(1, ...series.map((s) => s.value)), [series]);
  const groups = useMemo(() => {
    const map = new Map<string, OpsMetricSeries[]>();
    for (const s of series) {
      const arr = map.get(s.name) ?? [];
      arr.push(s);
      map.set(s.name, arr);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [series]);

  return (
    <ul className="ops-metrics-groups" aria-label="Metric series">
      {groups.map(([name, items], groupIndex) => (
        <li key={name} className="ops-metrics-group">
          <div className="ops-metrics-group-header">
            <span className="ops-metrics-group-name">{name}</span>
            <span className="ops-metrics-group-count">{items.length} series</span>
          </div>
          <ul className="ops-metrics-series-list">
            {items.map((s, i) => {
              const labelKey = Object.entries(s.labels)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([k, v]) => `${k}=${v}`)
                .join("|");
              const heat = metricHeatLevel(s.value, max);
              const share = max > 0 ? (s.value / max) * 100 : 0;
              const staggerIndex = clamp(groupIndex * 2 + i, 0, MAX_STAGGER_NODES - 1);
              return (
                <li
                  key={labelKey}
                  className={`ops-metric-series ${reduced ? "" : "ops-metric-series-enter"}`}
                  style={{ animationDelay: `${staggerIndex * STAGGER_MS}ms` }}
                >
                  <div className="ops-metric-series-labels">
                    <Labels labels={s.labels} />
                  </div>
                  <div className="ops-metric-series-value">
                    <span className={`ops-metric-value-number ops-heat-${heat}`}>
                      {s.value.toLocaleString()}
                    </span>
                    <div className="ops-metric-bar-bg" aria-hidden="true">
                      <div
                        className={`ops-metric-bar ops-metric-bar-${heat}`}
                        style={{ width: `${share}%` }}
                      />
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ul>
  );
}

function Traces({ traces }: { traces: readonly OpsTrace[] }) {
  const reduced = usePrefersReducedMotion();
  if (traces.length === 0) {
    return (
      <div className="ops-empty-state">
        <Timer size={24} aria-hidden="true" />
        <p>No recent traces.</p>
      </div>
    );
  }

  const starts = traces.map((t) => new Date(t.start_time).getTime());
  const durations = traces.map((t) => t.duration_ms);
  const timeAxisReady = starts.every((s) => !Number.isNaN(s));
  const min = timeAxisReady ? Math.min(...starts) : 0;
  const maxEnd = timeAxisReady ? Math.max(...starts.map((s, i) => s + durations[i])) : 0;
  const scale = Math.max(1, maxEnd - min);
  const maxDuration = Math.max(1, ...durations);

  const tickCount = 4;
  const ticks = Array.from({ length: tickCount }, (_, i) => min + (scale * i) / (tickCount - 1));

  return (
    <div className="ops-traces-timeline">
      {timeAxisReady && (
        <div className="ops-traces-axis" aria-hidden="true">
          <div className="ops-traces-axis-line" />
          {ticks.map((tick, i) => (
            <span
              key={`tick-${tick}`}
              className="ops-traces-axis-tick"
              style={{ left: `${(i / (tickCount - 1)) * 100}%` }}
            >
              {fmtTime(new Date(tick).toISOString())}
            </span>
          ))}
        </div>
      )}
      <ul className="ops-trace-rows" aria-label="Recent traces">
        {traces.map((t, i) => {
          const start = new Date(t.start_time).getTime();
          const latency = traceLatencyClass(t.duration_ms);
          const left = timeAxisReady ? ((start - min) / scale) * 100 : 0;
          const width = timeAxisReady ? (t.duration_ms / scale) * 100 : 0;
          const simpleWidth = (t.duration_ms / maxDuration) * 100;
          const staggerIndex = clamp(i, 0, MAX_STAGGER_NODES - 1);
          return (
            <li key={t.trace_id} className="ops-trace-row-item">
              <button
                type="button"
                className={`ops-trace-row ${reduced ? "" : "ops-trace-row-enter"}`}
                style={{ animationDelay: `${staggerIndex * STAGGER_MS}ms` }}
                aria-label={`Trace ${t.trace_id}: ${t.root_name} in ${t.service}, ${t.duration_ms} ms`}
              >
                <div className="ops-trace-row-main">
                  <div className="ops-trace-row-meta">
                    <span className="ops-trace-row-service">{t.service}</span>
                    <span className="ops-trace-row-name" title={t.root_name}>
                      {t.root_name}
                    </span>
                  </div>
                  <div className="ops-trace-bar-bg" aria-hidden="true">
                    <div
                      className={`ops-trace-bar ops-trace-bar-time ops-trace-bar-${latency}`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                    />
                    <div
                      className={`ops-trace-bar ops-trace-bar-simple ops-trace-bar-${latency}`}
                      style={{ width: `${simpleWidth}%` }}
                    />
                  </div>
                  <span className={`ops-trace-row-duration ops-trace-duration-${latency}`}>
                    {t.duration_ms.toLocaleString()} ms
                  </span>
                </div>
                <div className="ops-trace-row-detail">
                  <span className="ops-trace-detail-id" title={t.trace_id}>
                    {t.trace_id}
                  </span>
                  <span className="ops-trace-detail-start">{fmtTime(t.start_time)}</span>
                  <span className="ops-trace-detail-service">{t.service}</span>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import {
  Activity,
  AlertTriangle,
  ChevronDown,
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
  type OpsVersions,
} from "@/lib/ops-api";
import {
  subscribeOpsStream,
  type OpsStreamSection,
  type OpsStreamStatus,
} from "@/lib/ops-stream";

const REFRESH_INTERVAL_MS = 30_000;
const STAGGER_MS = 35;
const MAX_STAGGER_NODES = 8;
const MAX_AUDIT_BLOCKS = 14;
const COUNT_UP_MS = 250;

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

const activeField = (
  section: OpsConsoleProps["section"],
): keyof OpsSnapshot | null => {
  if (!section) return null;
  if (section === "overview") return "overview";
  if (section === "metrics") return "metrics";
  if (section === "traces") return "traces";
  return "audit";
};

const mergeWithFallback = (
  streamData: OpsSnapshot,
  fetched: OpsSnapshot,
  section: OpsConsoleProps["section"],
): OpsSnapshot => {
  const field = activeField(section);
  if (!field) return fetched;
  return { ...fetched, [field]: streamData[field] ?? fetched[field] };
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

const HIDDEN_METRIC_LABELS = new Set([
  "instance",
  "service_instance_id",
  "job",
  "service_name",
]);

function MetricLabels({ labels }: { labels: Readonly<Record<string, string>> }) {
  const entries = Object.entries(labels).filter(([k]) => !HIDDEN_METRIC_LABELS.has(k));
  if (entries.length === 0) {
    return <span className="ops-signal-series-label ops-signal-series-label-none">none</span>;
  }
  return (
    <div className="ops-signal-series-labels">
      {entries.map(([k, v]) => {
        const text = `${k}=${v}`;
        return (
          <span key={k} className="ops-signal-series-label" title={text}>
            {text}
          </span>
        );
      })}
    </div>
  );
}

function seriesKey(s: OpsMetricSeries): string {
  const visible = Object.entries(s.labels)
    .filter(([k]) => !HIDDEN_METRIC_LABELS.has(k))
    .sort(([a], [b]) => a.localeCompare(b));
  return `${s.name}||${JSON.stringify(visible)}`;
}

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

function useAnimatedValue(target: number, duration: number, reduced: boolean): number {
  const [animated, setAnimated] = useState(target);
  const displayRef = useRef(target);
  const rafRef = useRef(0);

  useEffect(() => {
    if (reduced) {
      displayRef.current = target;
      cancelAnimationFrame(rafRef.current);
      return;
    }
    const from = displayRef.current;
    if (from === target) return;
    const start = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      const eased = 1 - (1 - progress) ** 3;
      const value = Math.round(from + (target - from) * eased);
      displayRef.current = value;
      setAnimated(value);
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(step);
      } else {
        displayRef.current = target;
      }
    };
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, duration, reduced]);

  return reduced ? target : animated;
}

function AnimatedNumber({
  value,
  reduced,
  className,
}: {
  value: number;
  reduced: boolean;
  className?: string;
}) {
  const display = useAnimatedValue(value, COUNT_UP_MS, reduced);
  return <span className={className}>{display.toLocaleString()}</span>;
}

function SignalRail({ alive }: { alive: boolean }) {
  return (
    <div className={`ops-signal-rail ${alive ? "ops-signal-rail-alive" : "ops-signal-rail-dead"}`} aria-hidden="true">
      <svg preserveAspectRatio="none" viewBox="0 0 1200 24" aria-hidden="true">
        <polyline
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

function HeroVerdict({ status, checkedAt }: { status: string; checkedAt: string | null }) {
  const reduced = usePrefersReducedMotion();
  const ok = status === "ok";
  const degraded = status === "degraded";
  const toneClass = ok ? "ops-hero-ok" : degraded ? "ops-hero-degraded" : "ops-hero-unknown";
  const label = `Platform ${status}`;
  return (
    <div className={`ops-hero-verdict ${toneClass}`} aria-live="polite" aria-atomic="true">
      <svg viewBox="0 0 200 200" aria-hidden="true" className="ops-hero-dial">
        <circle className="ops-dial-track" cx="100" cy="100" r="80" />
        <circle className={`ops-dial-arc ${reduced ? "" : "ops-dial-arc-sweep"}`} cx="100" cy="100" r="80" />
        <circle className="ops-dial-knob" cx="100" cy="20" r="6" />
      </svg>
      <span className="ops-hero-state">{label}</span>
      <span className="ops-hero-checked">Checked {fmtRel(checkedAt)}</span>
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

function componentStat(name: string, versions: OpsVersions | null): string {
  if (!versions) return "";
  if (name === "rules") return versions.engine_rule_version;
  if (name === "api") return versions.service_name;
  if (name === "database") return versions.schema_revision ?? "";
  return "";
}

function freshnessWidth(iso: string): number {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 50;
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return 100;
  if (s < 600) return clamp(Math.round(100 - ((s - 60) / 540) * 85), 15, 100);
  return 15;
}

function SignalMap({
  components,
  sources,
  versions,
}: {
  components: readonly { name: string; state: string; detail: string | null }[];
  sources: readonly { name: string; state: string; detail: string | null; last_data_at: string | null }[];
  versions: OpsVersions | null;
}) {
  const reduced = usePrefersReducedMotion();

  return (
    <div className="ops-signal-map">
      <div className="ops-signal-bus" aria-hidden="true">
        <div className="ops-signal-node ops-signal-node-platform" aria-hidden="true">
          <span className="ops-signal-node-dot" />
          <span className="ops-signal-node-name">platform</span>
        </div>
        <div className="ops-signal-bus-line" aria-hidden="true" />
      </div>

      <div className="ops-signal-map-content">
        <section className="ops-spine-section" aria-label="Components">
          <h2 className="ops-panel-title">Components</h2>
          <ul className="ops-spine-list">
            {components.map((c, i) => (
              <SignalNode
                key={c.name}
                node={{ ...c, kind: "component" }}
                index={i}
                versions={versions}
                reduced={reduced}
              />
            ))}
            {components.length === 0 && (
              <li className="ops-empty">No components reported.</li>
            )}
          </ul>
        </section>

        <section className="ops-spine-section" aria-label="Sources">
          <h2 className="ops-panel-title">Source freshness</h2>
          <ul className="ops-spine-list">
            {sources.map((s, i) => (
              <SignalNode
                key={s.name}
                node={{ ...s, kind: "source" }}
                index={i + components.length}
                versions={versions}
                reduced={reduced}
              />
            ))}
            {sources.length === 0 && (
              <li className="ops-empty">No sources reported.</li>
            )}
          </ul>
        </section>
      </div>
    </div>
  );
}

function SignalNode({
  node,
  index,
  versions,
  reduced,
}: {
  node: SignalMapNode;
  index: number;
  versions: OpsVersions | null;
  reduced: boolean;
}) {
  const t = tone(node.state);
  const stale = node.state === "stale";
  const unavailable = node.state === "unavailable";
  const micro =
    node.kind === "source"
      ? node.last_data_at
        ? fmtRel(node.last_data_at)
        : ""
      : componentStat(node.name, versions);
  const freshness =
    node.kind === "source" && node.last_data_at
      ? freshnessWidth(node.last_data_at)
      : 100;
  const delay = reduced
    ? "0ms"
    : `${clamp(index, 0, MAX_STAGGER_NODES - 1) * STAGGER_MS}ms`;

  return (
    <li
      className={`ops-spine-row ops-spine-row-${t} ${stale ? "ops-spine-row-stale" : ""} ${unavailable ? "ops-spine-row-unavailable" : ""} ${reduced ? "" : "ops-spine-row-enter"}`}
      style={
        {
          "--row-delay": delay,
          "--freshness": `${freshness}%`,
        } as React.CSSProperties
      }
    >
      <div className="ops-spine-row-main">
        <span className="ops-spine-led" aria-hidden="true">
          <span
            className={`ops-spine-led-dot ${reduced ? "" : "ops-spine-led-pulse"}`}
          />
        </span>
        <span className="ops-spine-name">{node.name}</span>
        {micro && (
          <>
            <span className="ops-spine-separator" aria-hidden="true">
              ·
            </span>
            <span className="ops-spine-stat">{micro}</span>
          </>
        )}
        <span className="ops-spine-state">
          <StateBadge state={node.state} />
        </span>
      </div>
      <div className="ops-spine-bar" aria-hidden="true">
        <div className="ops-spine-bar-fill" />
      </div>
    </li>
  );
}

function HashChain({ intact, eventCount, checkedAt }: { intact: boolean; eventCount: number; checkedAt: string }) {
  const reduced = usePrefersReducedMotion();
  const displayed = eventCount > 0 ? clamp(Math.min(eventCount, MAX_AUDIT_BLOCKS), 1, MAX_AUDIT_BLOCKS) : 0;
  const remainder = Math.max(0, eventCount - displayed);
  const breakIndex = displayed > 0 ? Math.floor(displayed / 2) : 0;

  const blocks = Array.from({ length: displayed }, (_, i) => ({
    id: `audit-block-${i}`,
    fragment: `b${i.toString(16).padStart(2, "0")}`,
    fallen: !intact && i >= breakIndex,
  }));

  return (
    <section
      className={`ops-audit-surface ${intact ? "ops-audit-intact" : "ops-audit-broken"}`}
      aria-label="Audit integrity"
    >
      <div className="ops-audit-hero">
        <div className="ops-audit-count">
          <AnimatedNumber
            value={eventCount}
            reduced={reduced}
            className="ops-audit-count-value"
          />
          <span className="ops-audit-count-label">events</span>
        </div>
        <time className="ops-audit-checked" dateTime={checkedAt}>
          {fmtRel(checkedAt)}
        </time>
      </div>

      <div className="ops-audit-chain" aria-hidden="true">
        <div className={`ops-audit-chain-line ${intact ? "" : "ops-audit-chain-line-broken"}`} />
        {!reduced && intact && <div className="ops-audit-chain-sweep" />}
        <div className="ops-audit-blocks">
          {blocks.map((block, i) => (
            <div
              key={block.id}
              className={`ops-audit-block ${block.fallen ? "ops-audit-block-fallen" : ""} ${reduced ? "" : "ops-audit-block-enter"}`}
              style={{ "--block-index": i } as React.CSSProperties}
            >
              {i > 0 && (
                <span className="ops-audit-link-mark" aria-hidden="true">
                  <svg viewBox="0 0 16 6" aria-hidden="true">
                    <line
                      x1="0"
                      y1="3"
                      x2="16"
                      y2="3"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                    />
                  </svg>
                </span>
              )}
              <span className="ops-audit-fragment">{block.fragment}</span>
            </div>
          ))}
          {remainder > 0 && (
            <span className="ops-audit-more">+{remainder.toLocaleString()}</span>
          )}
        </div>
      </div>

      <div className="ops-audit-verdict">
        <h2>{intact ? "Audit chain intact" : "Audit chain integrity failure"}</h2>
        {!intact && (
          <span>Audit ledger integrity check failed. Escalate immediately.</span>
        )}
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

function LiveIndicator({
  status,
  reduced,
}: {
  status: OpsStreamStatus;
  reduced: boolean;
}) {
  const toneClass =
    status === "live"
      ? "ops-live-indicator-live"
      : status === "reconnecting"
        ? "ops-live-indicator-reconnecting"
        : "ops-live-indicator-offline";

  return (
    <span
      className={`ops-live-indicator ${toneClass}`}
      role="status"
      aria-label="Stream status"
      title={`Stream: ${status}`}
    >
      <span
        className={`ops-live-dot ${status === "live" && !reduced ? "ops-live-dot-pulse" : ""}`}
        aria-hidden="true"
      />
      <span>{status}</span>
    </span>
  );
}

export function OpsConsole({ variant = "page", section }: OpsConsoleProps) {
  const [window, setWindow] = useState<OpsWindow>("5m");
  const [snap, setSnap] = useState<Loadable<OpsSnapshot>>({ state: "loading" });
  const [busy, setBusy] = useState(false);
  const [streamStatus, setStreamStatus] = useState<OpsStreamStatus>("connecting");
  const embedded = variant === "embedded";
  const reduced = usePrefersReducedMotion();

  const mergeSnapshot = useCallback(
    (streamSection: OpsStreamSection, payload: unknown) => {
      setSnap((prev) => {
        if (prev.state !== "ok") {
          // `overview` is mandatory in OpsSnapshot (it drives the verdict), and
          // every fetch includes it. A first snapshot for another section is
          // therefore held until the initial fetch lands - which is why that
          // fetch must never be aborted (see the load effect below).
          if (streamSection !== "overview") return prev;
          return {
            state: "ok",
            data: {
              overview: payload as OpsOverviewResponse,
              metrics: null,
              traces: null,
              audit: null,
            },
          };
        }
        const next = { ...prev.data };
        if (streamSection === "overview") {
          next.overview = payload as OpsOverviewResponse;
        } else if (streamSection === "metrics") {
          next.metrics = payload as OpsMetricsResponse;
        } else if (streamSection === "traces") {
          next.traces = payload as OpsTracesResponse;
        } else if (streamSection === "audit") {
          next.audit = payload as OpsAuditResponse;
        }
        return { state: "ok", data: next };
      });
    },
    [],
  );

  useEffect(() => {
    if (typeof WebSocket === "undefined") {
      setStreamStatus("offline");
      return;
    }
    const streamSection: OpsStreamSection = section ?? "overview";
    return subscribeOpsStream({
      section: streamSection,
      window,
      onSnapshot: (snapshot) => mergeSnapshot(snapshot.section, snapshot.payload),
      onStatus: setStreamStatus,
    });
  }, [section, window, mergeSnapshot]);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      setBusy(true);
      try {
        const data = await fetchSnapshot(window, section, signal);
        setSnap((prev) =>
          prev.state === "ok" && streamStatus === "live"
            ? { state: "ok", data: mergeWithFallback(prev.data, data, section) }
            : { state: "ok", data },
        );
      } catch (err) {
        setSnap((prev) =>
          prev.state === "ok" ? prev : { state: "error", message: fetchErrorMessage(err) },
        );
      } finally {
        setBusy(false);
      }
    },
    [window, section, streamStatus],
  );

  const loadOnce = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const data = await fetchSnapshot(window, section, signal);
        if (signal?.aborted) return;
        setSnap((prev) =>
          prev.state === "ok"
            ? { state: "ok", data: mergeWithFallback(prev.data, data, section) }
            : { state: "ok", data },
        );
      } catch (err) {
        if (signal?.aborted) return;
        setSnap((prev) =>
          prev.state === "ok" ? prev : { state: "error", message: fetchErrorMessage(err) },
        );
      }
    },
    [window, section],
  );

  useEffect(() => {
    // First paint must not depend on the socket, and must NOT be aborted when
    // the stream flips to `live`. Aborting it there is half of why a freshly
    // opened page stayed blank until Refresh: the socket went live and killed
    // the in-flight first fetch before it could render.
    const controller = new AbortController();
    void loadOnce(controller.signal);
    return () => controller.abort();
  }, [loadOnce]);

  useEffect(() => {
    // The socket is the primary source while it is live; this interval is only
    // the fallback for when it is down or reconnecting.
    if (streamStatus === "live") return;
    const controller = new AbortController();
    const id = setInterval(() => void loadOnce(controller.signal), REFRESH_INTERVAL_MS);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, [loadOnce, streamStatus]);

  const status = snap.state === "ok" ? snap.data.overview.status : "unknown";
  const checkedAt = snap.state === "ok" ? snap.data.overview.checked_at : null;
  const sectionMeta = section ? SECTION_TITLES[section] : { title: "Operations Console", subtitle: "Technical reviewer operations overview" };

  const showOverview = !section || section === "overview";
  const showMetrics = !section || section === "metrics";
  const showTraces = !section || section === "traces";
  const showAudit = !section || section === "audit";

  return (
    <div className={`ops-dark ${embedded ? "ops-dark-embedded" : ""}`}>
      <SignalRail alive={snap.state === "ok"} />
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
                <span className="ops-subtitle">{sectionMeta.subtitle}</span>
              </div>
            </div>
            {!showOverview && <VerdictGauge status={status} />}
          </div>
          <div className="ops-header-meta">
            <LiveIndicator status={streamStatus} reduced={reduced} />
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
              <section className="ops-signal-wall" aria-label="Metrics">
                <div className="ops-signal-wall-controls">
                  <span className="ops-signal-wall-updated">—</span>
                  <WindowSwitch value={window} onChange={setWindow} />
                </div>
                <MetricsSkeleton />
              </section>
            )}
            {showTraces && (
              <section className="ops-traces-surface" aria-label="Traces">
                <div className="ops-traces-strip">
                  <span className="ops-traces-strip-title">Traces</span>
                  <div className="ops-traces-figures">
                    <span className="ops-traces-figure">
                      total <strong>—</strong>
                    </span>
                    <span className="ops-traces-figure">
                      slowest <strong>—</strong>
                    </span>
                  </div>
                </div>
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
                <div className="ops-overview-grid">
                  <div className="ops-overview-hero">
                    <HeroVerdict status={status} checkedAt={checkedAt} />
                  </div>
                  <SignalMap
                    components={snap.data.overview.components}
                    sources={snap.data.overview.sources}
                    versions={snap.data.overview.versions}
                  />
                </div>

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
              <section className="ops-signal-wall" aria-label="Metrics">
                <div className="ops-signal-wall-controls">
                  <span
                    className="ops-signal-wall-updated"
                    title={snap.data.metrics.source.last_data_at ?? snap.data.overview.checked_at}
                  >
                    Updated {fmtRel(snap.data.metrics.source.last_data_at ?? snap.data.overview.checked_at)}
                  </span>
                  <WindowSwitch value={window} onChange={setWindow} />
                </div>
                {snap.data.metrics.series.length === 0 ? (
                  <div className="ops-empty-state">
                    <Activity size={24} aria-hidden="true" />
                    <p>No metrics available for this window.</p>
                  </div>
                ) : (
                  <MetricsTable metrics={snap.data.metrics} />
                )}
              </section>
            )}

            {showTraces && snap.data.traces && (
              <section className="ops-traces-surface" aria-label="Traces">
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

const SKEL_BANDS = ["a", "b", "c"];
const SKEL_SERIES = ["1", "2", "3", "4"];
const COLLAPSED_PREVIEW_COUNT = 3;

function usePreviousMetricValues(series: readonly OpsMetricSeries[]): ReadonlyMap<string, number> {
  const previousRef = useRef<ReadonlyMap<string, number>>(new Map());
  const current = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of series) {
      map.set(seriesKey(s), s.value);
    }
    return map;
  }, [series]);
  // This ref is a render-to-render scratchpad for value-change detection only.
  // eslint-disable-next-line react-hooks/refs
  const previous = previousRef.current;
  useEffect(() => {
    previousRef.current = current;
  }, [current]);
  return previous;
}

function rankLabel(index: number, total: number): string {
  if (total === 1) return "1 series";
  if (index === 0) return "largest";
  if (index === 1) return "2nd";
  if (index === 2) return "3rd";
  return `${index + 1}th`;
}

function MetricsSkeleton() {
  return (
    <ul className="ops-metric-cards" aria-hidden="true">
      {SKEL_BANDS.map((bandId) => (
        <li key={`skel-card-${bandId}`} className="ops-metric-card">
          <div className="ops-metric-card-header">
            <div className="ops-skeleton-line" style={{ width: "160px" }} />
            <div className="ops-skeleton-line" style={{ width: "80px" }} />
          </div>
          <div className="ops-metric-summary-row">
            {SKEL_SERIES.slice(0, COLLAPSED_PREVIEW_COUNT).map((seriesId) => (
              <div key={`skel-summary-${bandId}-${seriesId}`} className="ops-metric-summary-item">
                <div className="ops-skeleton-value" />
                <div className="ops-skeleton-line" style={{ width: "70%" }} />
                <div className="ops-metric-summary-bar-wrap">
                  <div className="ops-skeleton-bar" />
                </div>
              </div>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

type MetricSummaryItemProps = {
  series: OpsMetricSeries;
  groupMax: number;
  changed: boolean;
  reduced: boolean;
};

function MetricSummaryItem({ series, groupMax, changed, reduced }: MetricSummaryItemProps) {
  const share = groupMax > 0 ? series.value / groupMax : 0;
  const heat = metricHeatLevel(series.value, groupMax);
  return (
    <div className={`ops-metric-summary-item ${changed ? "ops-metric-summary-item-changed" : ""}`}>
      <AnimatedNumber
        value={series.value}
        reduced={reduced}
        className={`ops-metric-summary-value ops-signal-heat-${heat}`}
      />
      <MetricLabels labels={series.labels} />
      <div className="ops-metric-summary-bar-wrap" aria-hidden="true">
        <div
          className={`ops-metric-summary-bar ops-signal-bar-${heat} ${reduced ? "" : "ops-metric-bar-enter"}`}
          style={{ "--bar-share": String(share) } as React.CSSProperties}
        />
      </div>
    </div>
  );
}

type MetricSeriesRowProps = {
  series: OpsMetricSeries;
  groupMax: number;
  changed: boolean;
  reduced: boolean;
  index: number;
};

function MetricSeriesRow({ series, groupMax, changed, reduced }: MetricSeriesRowProps) {
  const share = groupMax > 0 ? series.value / groupMax : 0;
  const heat = metricHeatLevel(series.value, groupMax);
  return (
    <li className={`ops-metric-series-row ${changed ? "ops-metric-series-row-changed" : ""}`}>
      <div className="ops-metric-series-row-label">
        <MetricLabels labels={series.labels} />
      </div>
      <div className="ops-metric-series-row-value">
        <AnimatedNumber
          value={series.value}
          reduced={reduced}
          className={`ops-metric-series-value ops-signal-heat-${heat}`}
        />
      </div>
      <div className="ops-metric-series-row-bar" aria-hidden="true">
        <div
          className={`ops-metric-series-bar ops-signal-bar-${heat}`}
          style={{ "--bar-share": String(share) } as React.CSSProperties}
        />
      </div>
    </li>
  );
}

type MetricCardProps = {
  name: string;
  items: readonly OpsMetricSeries[];
  groupMax: number;
  changedMap: ReadonlyMap<string, boolean>;
  source: import("@/lib/ops-api").OpsSource;
  window: import("@/lib/ops-api").OpsWindow;
  reduced: boolean;
  groupIndex: number;
};

function MetricCard({
  name,
  items,
  groupMax,
  changedMap,
  source,
  window,
  reduced,
  groupIndex,
}: MetricCardProps) {
  const [expanded, setExpanded] = useState(false);
  const anyChanged = items.some((s) => changedMap.get(seriesKey(s)) ?? false);
  const statusText = useMemo(() => {
    const total = items.length;
    const rank = rankLabel(0, total);
    const suffix = anyChanged ? " • changed" : "";
    return total === 1 ? `${rank}${suffix}` : `${rank} of ${total}${suffix}`;
  }, [items.length, anyChanged]);

  const cardDelay = reduced ? "0ms" : `${clamp(groupIndex, 0, MAX_STAGGER_NODES - 1) * STAGGER_MS}ms`;

  return (
    <li
      className={`ops-metric-card ${reduced ? "" : "ops-metric-card-enter"}`}
      data-changed={anyChanged}
      style={{ "--card-delay": cardDelay } as React.CSSProperties}
    >
      <button
        type="button"
        className="ops-metric-card-header"
        onClick={() => setExpanded((e) => !e)}
        aria-expanded={expanded}
        aria-label={expanded ? `Collapse ${name}` : `Expand ${name}`}
      >
        <span className="ops-metric-card-name">{name}</span>
        <span className="ops-metric-card-status">{statusText}</span>
        <ChevronDown
          size={18}
          aria-hidden="true"
          className={`ops-metric-card-chevron ${expanded ? "ops-metric-card-chevron-open" : ""}`}
        />
      </button>

      <div
        className={`ops-metric-card-summary ${expanded ? "ops-metric-card-summary-hidden" : ""}`}
        aria-hidden={expanded}
      >
        <div className="ops-metric-summary-row">
          {items.slice(0, COLLAPSED_PREVIEW_COUNT).map((s) => (
            <MetricSummaryItem
              key={seriesKey(s)}
              series={s}
              groupMax={groupMax}
              changed={changedMap.get(seriesKey(s)) ?? false}
              reduced={reduced}
            />
          ))}
        </div>
      </div>

      <div
        className={`ops-metric-card-detail ${expanded ? "ops-metric-card-detail-open" : ""}`}
        aria-hidden={!expanded}
      >
        <div className="ops-metric-card-detail-inner">
          <ul className="ops-metric-series-list">
            {items.map((s, i) => (
              <MetricSeriesRow
                key={seriesKey(s)}
                series={s}
                groupMax={groupMax}
                changed={changedMap.get(seriesKey(s)) ?? false}
                reduced={reduced}
                index={i}
              />
            ))}
          </ul>
          <div className="ops-metric-card-meta">
            <span>window {window}</span>
            <span aria-hidden="true">·</span>
            <span>
              {source.name} {source.state}
            </span>
          </div>
        </div>
      </div>
    </li>
  );
}

function MetricsTable({ metrics }: { metrics: OpsMetricsResponse }) {
  const reduced = usePrefersReducedMotion();
  const previous = usePreviousMetricValues(metrics.series);
  const groups = useMemo(() => {
    const map = new Map<string, OpsMetricSeries[]>();
    for (const s of metrics.series) {
      const arr = map.get(s.name) ?? [];
      arr.push(s);
      map.set(s.name, arr);
    }
    return Array.from(map.entries())
      .map(([name, items]): [string, OpsMetricSeries[]] => {
        items.sort((a, b) => b.value - a.value);
        return [name, items];
      })
      .sort(([a], [b]) => a.localeCompare(b));
  }, [metrics.series]);

  const changedMap = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const s of metrics.series) {
      const key = seriesKey(s);
      map.set(key, previous.get(key) !== undefined && previous.get(key) !== s.value);
    }
    return map;
  }, [metrics.series, previous]);

  return (
    <ul className="ops-metric-cards" aria-label="Metric groups">
      {groups.map(([name, items], groupIndex) => {
        const groupMax = Math.max(1, ...items.map((s) => s.value));
        return (
          <MetricCard
            key={name}
            name={name}
            items={items}
            groupMax={groupMax}
            changedMap={changedMap}
            source={metrics.source}
            window={metrics.window}
            reduced={reduced}
            groupIndex={groupIndex}
          />
        );
      })}
    </ul>
  );
}

function Traces({ traces }: { traces: readonly OpsTrace[] }) {
  const reduced = usePrefersReducedMotion();
  const timeAxisReady = traces.length > 0 && traces.every((t) => !Number.isNaN(new Date(t.start_time).getTime()));
  const starts = traces.map((t) => new Date(t.start_time).getTime());
  const ends = traces.map((t, i) => starts[i] + t.duration_ms);
  const min = timeAxisReady ? Math.min(...starts) : 0;
  const max = timeAxisReady ? Math.max(...ends) : 1;
  const range = Math.max(1, max - min);
  const durations = traces.map((t) => t.duration_ms);
  const maxDuration = Math.max(1, ...durations);
  const slowest = durations.length > 0 ? Math.max(...durations) : 0;

  const ticks = (() => {
    if (!timeAxisReady) return [] as number[];
    if (range <= 0) return [min];
    const count = 5;
    return Array.from({ length: count }, (_, i) => min + (range * i) / (count - 1));
  })();

  return (
    <>
      <div className="ops-traces-strip">
        <span className="ops-traces-strip-title">Traces</span>
        <div className="ops-traces-figures">
          <span className="ops-traces-figure">
            total <AnimatedNumber value={traces.length} reduced={reduced} />
          </span>
          <span className="ops-traces-figure">
            slowest <AnimatedNumber value={slowest} reduced={reduced} /> ms
          </span>
        </div>
      </div>

      {traces.length === 0 ? (
        <div className="ops-traces-empty">
          <Timer size={24} aria-hidden="true" className="ops-traces-empty-icon" />
          <span>No recent traces.</span>
        </div>
      ) : (
        <>
          {timeAxisReady && (
            <div className="ops-traces-ruler" aria-hidden="true">
              <div className="ops-traces-ruler-line" />
              {ticks.map((tick) => (
                <span
                  key={`tick-${tick}`}
                  className="ops-traces-ruler-tick"
                  style={{ left: `${range <= 0 ? 0 : ((tick - min) / range) * 100}%` }}
                >
                  {fmtTime(new Date(tick).toISOString())}
                </span>
              ))}
            </div>
          )}

          <div className="ops-traces-body">
            <ul className="ops-trace-rows" aria-label="Recent traces">
              {traces.map((t, i) => {
                const start = new Date(t.start_time).getTime();
                const latency = traceLatencyClass(t.duration_ms);
                const left = timeAxisReady ? ((start - min) / range) * 100 : 0;
                const width = timeAxisReady ? (t.duration_ms / range) * 100 : 0;
                const simpleWidth = (t.duration_ms / maxDuration) * 100;
                const staggerIndex = clamp(i, 0, MAX_STAGGER_NODES - 1);
                const delay = reduced ? "0ms" : `${staggerIndex * 25}ms`;
                return (
                  <li key={t.trace_id}>
                    <button
                      type="button"
                      className={`ops-trace-row ${reduced ? "" : "ops-trace-row-enter"}`}
                      style={{ "--row-delay": delay } as React.CSSProperties}
                      aria-label={`Trace ${t.trace_id}: ${t.root_name} in ${t.service}, ${t.duration_ms} ms`}
                    >
                      <div className="ops-trace-gutter">
                        <span className="ops-trace-gutter-name" title={t.root_name}>
                          {t.root_name}
                        </span>
                        <span className="ops-trace-gutter-service" title={t.service}>
                          {t.service}
                        </span>
                      </div>
                      <div className="ops-trace-track" aria-hidden="true">
                        <div
                          className={`ops-trace-bar ops-trace-bar-${latency} ${reduced ? "" : "ops-trace-bar-grow"}`}
                          style={{
                            left: `${left}%`,
                            "--bar-scale": String(width / 100),
                            "--bar-simple": `${simpleWidth}%`,
                            "--bar-delay": delay,
                          } as React.CSSProperties}
                        />
                      </div>
                      <span className="ops-trace-duration">
                        {t.duration_ms.toLocaleString()} ms
                      </span>
                      <div className="ops-trace-detail">
                        <span className="ops-trace-detail-id" title={t.trace_id}>
                          {t.trace_id}
                        </span>
                        <span className="ops-trace-detail-start">{fmtTime(t.start_time)}</span>
                        <span className="ops-trace-detail-service">{t.service}</span>
                        <span className="ops-trace-detail-duration">
                          {t.duration_ms.toLocaleString()} ms
                        </span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        </>
      )}
    </>
  );
}

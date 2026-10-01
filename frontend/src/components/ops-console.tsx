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
  Check,
  ChevronLeft,
  ChevronRight,
  Clock,
  LayoutDashboard,
  Pause,
  Play,
  RefreshCw,
  Timer,
  Users,
} from "lucide-react";
import {
  getOpsActivity,
  getOpsAudit,
  getOpsMetrics,
  getOpsOverview,
  getOpsRoles,
  getOpsTraces,
  type OpsActivityAction,
  type OpsActivityArea,
  type OpsActivityEntry,
  type OpsActivityResponse,
  type OpsAuditResponse,
  type OpsMetricSeries,
  type OpsMetricsResponse,
  type OpsOverviewResponse,
  type OpsRole,
  type OpsRolesResponse,
  type OpsTrace,
  type OpsTracesResponse,
  type OpsVersions,
  type OpsWindow,
} from "@/lib/ops-api";
import {
  subscribeOpsStream,
  type OpsStreamSection,
  type OpsStreamStatus,
} from "@/lib/ops-stream";

const REFRESH_INTERVAL_MS = 30_000;
const STAGGER_MS = 35;
const MAX_STAGGER_NODES = 8;
const AUDIT_CHAIN_LIMIT = 50;
const COUNT_UP_MS = 250;
const ACTIVITY_LIMIT = 50;

type ActivityFilters = {
  role: string | null;
  area: OpsActivityArea | null;
};

type Loadable<T> =
  | { state: "loading" }
  | { state: "ok"; data: T }
  | { state: "error"; message: string };
type OpsSnapshot = {
  overview: OpsOverviewResponse;
  metrics: OpsMetricsResponse | null;
  traces: OpsTracesResponse | null;
  audit: OpsAuditResponse | null;
  activity: OpsActivityResponse | null;
  roles: OpsRolesResponse | null;
};

const fetchSnapshot = async (
  window: OpsWindow,
  section: OpsConsoleProps["section"],
  activityFilters: ActivityFilters,
  signal?: AbortSignal,
): Promise<OpsSnapshot> => {
  if (section === "overview") {
    const overview = await getOpsOverview(signal);
    return { overview, metrics: null, traces: null, audit: null, activity: null, roles: null };
  }
  if (section === "metrics") {
    const [overview, metrics] = await Promise.all([
      getOpsOverview(signal),
      getOpsMetrics(window, signal),
    ]);
    return { overview, metrics, traces: null, audit: null, activity: null, roles: null };
  }
  if (section === "traces") {
    const [overview, traces] = await Promise.all([
      getOpsOverview(signal),
      getOpsTraces(25, signal),
    ]);
    return { overview, metrics: null, traces, audit: null, activity: null, roles: null };
  }
  if (section === "audit") {
    const [overview, audit] = await Promise.all([
      getOpsOverview(signal),
      getOpsAudit(signal),
    ]);
    return { overview, metrics: null, traces: null, audit, activity: null, roles: null };
  }
  if (section === "activity") {
    const [overview, activity] = await Promise.all([
      getOpsOverview(signal),
      getOpsActivity({ role: activityFilters.role, area: activityFilters.area, limit: ACTIVITY_LIMIT }, signal),
    ]);
    return { overview, metrics: null, traces: null, audit: null, activity, roles: null };
  }
  if (section === "roles") {
    const [overview, roles] = await Promise.all([
      getOpsOverview(signal),
      getOpsRoles(signal),
    ]);
    return { overview, metrics: null, traces: null, audit: null, activity: null, roles };
  }
  const [overview, metrics, traces, audit] = await Promise.all([
    getOpsOverview(signal),
    getOpsMetrics(window, signal),
    getOpsTraces(25, signal),
    getOpsAudit(signal),
  ]);
  return { overview, metrics, traces, audit, activity: null, roles: null };
};

const activeField = (
  section: OpsConsoleProps["section"],
): keyof OpsSnapshot | null => {
  if (!section) return null;
  if (section === "overview") return "overview";
  if (section === "metrics") return "metrics";
  if (section === "traces") return "traces";
  if (section === "audit") return "audit";
  if (section === "activity") return "activity";
  if (section === "roles") return "roles";
  return null;
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

function formatDuration(ms: number): string {
  // Use a fixed "." decimal separator and readable units so values like
  // 7.611 ms do not render as "7,611 ms" in comma-decimal locales, and so
  // sub-millisecond spans are shown in microseconds instead of long decimals.
  if (ms < 1) {
    const us = Math.round(ms * 1000);
    return us === 0 ? "0 µs" : `${us} µs`;
  }
  if (ms < 1000) {
    const whole = Math.floor(ms);
    const frac = ms - whole;
    if (frac < 0.05) return `${whole} ms`;
    return `${ms.toFixed(1)} ms`;
  }
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.floor((ms % 60_000) / 1000);
  if (seconds === 0) return `${minutes}m`;
  return `${minutes}m ${seconds}s`;
}

const TRACE_TITLE_MAP: Record<string, string> = {
  "GET /v1/health": "Health check",
  "GET /v1/claims": "Claim list",
  "POST /v1/claims": "Claim submitted",
  "GET /v1/queue": "Review queue",
  "GET /v1/auth/me": "Session check",
};

function traceTitle(rootName: string): string {
  const exact = TRACE_TITLE_MAP[rootName];
  if (exact) return exact;
  const path = rootName.replace(/^[A-Z]+\s+/, "");
  if (path.startsWith("/v1/operations/")) return "Operations API";
  return rootName;
}

type MetricCategory = {
  key: string;
  title: string;
  description: string;
  unit: string;
};

const METRIC_CATEGORIES: MetricCategory[] = [
  {
    key: "http",
    title: "HTTP requests",
    description: "How many requests the API handled, broken down by route, method, and result.",
    unit: "requests",
  },
  {
    key: "latency",
    title: "Latency",
    description: "How long requests take to complete across the API surface.",
    unit: "observations",
  },
  {
    key: "claims",
    title: "Claim submissions",
    description: "Claims submitted to the platform and whether they were new or duplicates.",
    unit: "claims",
  },
  {
    key: "decisions",
    title: "Review decisions",
    description: "Decisions recorded by reviewers on submitted claims.",
    unit: "decisions",
  },
  {
    key: "intake",
    title: "Intake jobs",
    description: "Document intake jobs and their processing outcome.",
    unit: "jobs",
  },
  {
    key: "assistant",
    title: "AI assistant turns",
    description: "Assistant responses and how each turn was resolved.",
    unit: "turns",
  },
  {
    key: "runtime",
    title: "Runtime health",
    description: "Process, host, and scraper health signals.",
    unit: "samples",
  },
  {
    key: "queue",
    title: "Queue & workers",
    description: "Background job and worker queue depth and throughput.",
    unit: "jobs",
  },
  {
    key: "database",
    title: "Database",
    description: "Database connection and query metrics.",
    unit: "samples",
  },
  {
    key: "other",
    title: "Other telemetry",
    description: "Additional metrics not grouped into a known category.",
    unit: "samples",
  },
];

function metricCategory(name: string): MetricCategory {
  const lower = name.toLowerCase();
  if (lower.includes("_duration_") || lower.includes("_latency_")) {
    return METRIC_CATEGORIES.find((c) => c.key === "latency")!;
  }
  if (lower.includes("claims_submitted")) {
    return METRIC_CATEGORIES.find((c) => c.key === "claims")!;
  }
  if (lower.includes("decisions")) {
    return METRIC_CATEGORIES.find((c) => c.key === "decisions")!;
  }
  if (lower.includes("intake_jobs")) {
    return METRIC_CATEGORIES.find((c) => c.key === "intake")!;
  }
  if (lower.includes("assistant_turns")) {
    return METRIC_CATEGORIES.find((c) => c.key === "assistant")!;
  }
  if (lower.startsWith("http_") || lower.includes("_http_")) {
    return METRIC_CATEGORIES.find((c) => c.key === "http")!;
  }
  if (
    lower === "up" ||
    lower.startsWith("scrape_") ||
    lower.startsWith("process_") ||
    lower.startsWith("node_") ||
    lower.startsWith("container_") ||
    lower.includes("memory") ||
    lower.includes("cpu")
  ) {
    return METRIC_CATEGORIES.find((c) => c.key === "runtime")!;
  }
  if (lower.includes("queue") || lower.includes("worker") || lower.includes("job")) {
    return METRIC_CATEGORIES.find((c) => c.key === "queue")!;
  }
  if (lower.startsWith("db_") || lower.startsWith("database_") || lower.includes("_sql_")) {
    return METRIC_CATEGORIES.find((c) => c.key === "database")!;
  }
  return METRIC_CATEGORIES.find((c) => c.key === "other")!;
}

const ROUTE_ACTIONS: Record<string, Record<string, string>> = {
  "/v1/claims": {
    GET: "Listing claims",
    POST: "Submitting a claim",
    PATCH: "Updating a claim",
    DELETE: "Deleting a claim",
  },
  "/v1/claims/{id}": {
    GET: "Reading a claim",
    PATCH: "Updating a claim",
    DELETE: "Deleting a claim",
  },
  "/v1/queue": { GET: "Loading the review queue" },
  "/v1/decisions": {
    GET: "Fetching decisions",
    POST: "Recording a decision",
  },
  "/v1/intake/jobs": {
    GET: "Listing intake jobs",
    POST: "Creating an intake job",
  },
  "/v1/intake/documents": { POST: "Uploading a document" },
  "/v1/assistant/turns": { POST: "Assistant conversation turn" },
  "/v1/operations/metrics": { GET: "Fetching metrics" },
  "/v1/operations/traces": { GET: "Fetching traces" },
  "/v1/health": { GET: "Health check" },
  "/v1/auth/me": { GET: "Session check" },
};

const STATUS_MEANING: Record<string, string> = {
  "2xx": "Successful — handled without error",
  "3xx": "Redirected — the caller was sent elsewhere",
  "4xx": "Rejected — the request was refused (e.g. not permitted)",
  "5xx": "Server error — failed inside the service",
};

const OUTCOME_MEANING: Record<string, Record<string, string>> = {
  claims: {
    submitted: "New claim recorded",
    duplicate: "Already seen — not counted twice",
  },
  decisions: {
    approved: "Approved",
    rejected: "Rejected",
    overridden: "Overridden by a lead",
  },
  intake: {
    needs_review: "Needs human review",
    rejected: "Rejected",
    submitted: "Submitted successfully",
  },
  assistant: {
    accepted: "Used as-is",
    repaired: "Corrected before use",
    fallback: "Answered by the deterministic layer, not the model",
    refused: "Refused — no answer given",
  },
};

const ACTION_MEANING: Record<string, string> = {
  confirm_issue: "Confirmed as a real issue",
  dismiss_with_reason: "Dismissed with a recorded reason",
  request_information: "More information requested",
  mark_corrected_for_recheck: "Marked corrected and rechecked",
};

function routeAction(route: string, method: string): string {
  const normalizedRoute = route ?? "";
  const normalizedMethod = (method ?? "").toUpperCase();
  const exact = ROUTE_ACTIONS[normalizedRoute]?.[normalizedMethod];
  if (exact) return exact;
  if (normalizedRoute.startsWith("/v1/")) {
    return `${normalizedMethod} ${normalizedRoute}`;
  }
  return normalizedRoute ? `${normalizedMethod} ${normalizedRoute}` : normalizedMethod;
}

const UNIT_SINGULAR: Record<string, string> = {
  requests: "request",
  observations: "observation",
  claims: "claim",
  decisions: "decision",
  jobs: "job",
  turns: "turn",
  samples: "sample",
};

function pluralUnit(count: number, unit: string): string {
  return count === 1 ? (UNIT_SINGULAR[unit] ?? unit) : unit;
}

function metricCategoryUnit(categoryKey: string): string {
  return METRIC_CATEGORIES.find((c) => c.key === categoryKey)?.unit ?? "samples";
}

type MetricLineDescription = {
  primary: string;
  secondary: string | null;
  raw: string;
};

function metricLineDescription(series: OpsMetricSeries): MetricLineDescription {
  const name = series.name.toLowerCase();
  const labels = series.labels;
  const raw = Object.entries(labels)
    .filter(([k]) => !HIDDEN_METRIC_LABELS.has(k))
    .map(([k, v]) => `${k}=${v}`)
    .join(", ");

  if (name.includes("http_requests_total")) {
    const action = routeAction(labels.route_template ?? labels.route ?? "", labels.method ?? "");
    const status = labels.status_class ? STATUS_MEANING[labels.status_class] ?? `status ${labels.status_class}` : null;
    return { primary: action, secondary: status, raw };
  }

  if (name.includes("http_request_duration")) {
    const action = routeAction(labels.route_template ?? labels.route ?? "", labels.method ?? "");
    return { primary: action, secondary: "Latency observation", raw };
  }

  if (labels.outcome) {
    let familyKey = "";
    if (name.includes("claims_submitted")) familyKey = "claims";
    else if (name.includes("decisions")) familyKey = "decisions";
    else if (name.includes("intake_jobs")) familyKey = "intake";
    else if (name.includes("assistant_turns")) familyKey = "assistant";

    if (familyKey) {
      const familyTitle = METRIC_CATEGORIES.find((c) => c.key === familyKey)?.title ?? familyKey;
      const meaning = OUTCOME_MEANING[familyKey]?.[labels.outcome] ?? `outcome ${labels.outcome}`;
      return { primary: familyTitle, secondary: meaning, raw };
    }
  }

  if (labels.action) {
    const familyTitle = name.includes("decisions")
      ? (METRIC_CATEGORIES.find((c) => c.key === "decisions")?.title ?? "Review decision")
      : "Action";
    const meaning = ACTION_MEANING[labels.action] ?? `action ${labels.action}`;
    return { primary: familyTitle, secondary: meaning, raw };
  }

  return { primary: series.name, secondary: raw || null, raw };
}

type TraceCategory = {
  key: string;
  title: string;
  description: string;
};

function traceCategory(rootName: string): TraceCategory {
  const method = rootName.split(" ")[0] ?? "";
  const path = rootName.replace(/^[A-Z]+\s+/, "").toLowerCase();
  if (path.startsWith("/v1/claims") && method === "POST") {
    return {
      key: "claim_submission",
      title: "Claim submission",
      description: "Requests that create or submit new claims.",
    };
  }
  if (path.startsWith("/v1/claims")) {
    return {
      key: "claims",
      title: "Claim queries",
      description: "Requests that read or list claim data.",
    };
  }
  if (path.startsWith("/v1/queue") || path.includes("/review") || path.includes("/decision")) {
    return {
      key: "review",
      title: "Review decisions",
      description: "Requests that fetch or record review decisions.",
    };
  }
  if (path.startsWith("/v1/intake") || path.includes("/documents") || path.includes("/upload")) {
    return {
      key: "intake",
      title: "Intake",
      description: "Document and intake ingestion requests.",
    };
  }
  if (path.startsWith("/v1/auth")) {
    return {
      key: "auth",
      title: "Authentication",
      description: "Sign-in, session, and authentication checks.",
    };
  }
  if (path.startsWith("/v1/health") || path.startsWith("/v1/operations")) {
    return {
      key: "ops",
      title: "Operations & health",
      description: "Health checks and operations telemetry endpoints.",
    };
  }
  return {
    key: "other",
    title: "Other requests",
    description: "Requests that do not belong to a known business category.",
  };
}

type OpsConsoleProps = {
  variant?: "page" | "embedded";
  section?: "overview" | "metrics" | "traces" | "audit" | "activity" | "roles";
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

const GAUGE_CIRCUMFERENCE = 94.25;

function VerdictGauge({ status }: { status: string }) {
  const reduced = usePrefersReducedMotion();
  const ok = status === "ok";
  const degraded = status === "degraded";
  const toneClass = ok ? "ops-gauge-ok" : degraded ? "ops-gauge-degraded" : "ops-gauge-unknown";
  const label = `Platform ${status}`;
  const zoneLen = GAUGE_CIRCUMFERENCE / 3;
  return (
    <div className={`ops-verdict-gauge ${toneClass}`} aria-live="polite" aria-atomic="true">
      <svg viewBox="0 0 40 40" aria-hidden="true" className="ops-gauge-face">
        <circle className="ops-gauge-track" cx="20" cy="20" r="15" />
        <g className="ops-gauge-zones">
          <circle
            className="ops-gauge-zone ops-gauge-zone-success"
            cx="20"
            cy="20"
            r="15"
            strokeDasharray={`${zoneLen} ${GAUGE_CIRCUMFERENCE - zoneLen}`}
            strokeDashoffset="0"
          />
          <circle
            className="ops-gauge-zone ops-gauge-zone-warning"
            cx="20"
            cy="20"
            r="15"
            strokeDasharray={`${zoneLen} ${GAUGE_CIRCUMFERENCE - zoneLen}`}
            strokeDashoffset={GAUGE_CIRCUMFERENCE - zoneLen}
          />
          <circle
            className="ops-gauge-zone ops-gauge-zone-danger"
            cx="20"
            cy="20"
            r="15"
            strokeDasharray={`${zoneLen} ${GAUGE_CIRCUMFERENCE - zoneLen}`}
            strokeDashoffset={GAUGE_CIRCUMFERENCE - zoneLen * 2}
          />
        </g>
        <g className="ops-gauge-ticks">
          <line className="ops-gauge-tick" x1="20" y1="2" x2="20" y2="5" />
          <line className="ops-gauge-tick" x1="38" y1="20" x2="35" y2="20" />
          <line className="ops-gauge-tick" x1="20" y1="38" x2="20" y2="35" />
          <line className="ops-gauge-tick" x1="2" y1="20" x2="5" y2="20" />
        </g>
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

type AuditChainSurfaceProps = {
  audit: OpsAuditResponse;
  reduced: boolean;
};

type AuditChainState =
  | { state: "loading" }
  | { state: "ok"; data: AuditChainResponse }
  | { state: "error"; message: string };

function groupAuditLinks(links: readonly AuditChainLink[]) {
  const groups: { claimRef: string; traceId: string; links: AuditChainLink[] }[] = [];
  for (const link of links) {
    const last = groups[groups.length - 1];
    if (last && last.claimRef === link.claim_ref) {
      last.links.push(link);
    } else {
      groups.push({ claimRef: link.claim_ref, traceId: link.trace_id, links: [link] });
    }
  }
  return groups;
}

function AuditChainSurface({ audit, reduced }: AuditChainSurfaceProps) {
  const [chain, setChain] = useState<AuditChainState>({ state: "loading" });
  const [paused, setPaused] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (paused) return;
    const controller = new AbortController();
    const load = async () => {
      setChain({ state: "loading" });
      try {
        const data = await fetchAuditChain(AUDIT_CHAIN_LIMIT, controller.signal);
        setChain({ state: "ok", data });
      } catch (err) {
        if (controller.signal.aborted) return;
        setChain({ state: "error", message: fetchErrorMessage(err) });
      }
    };
    void load();
    const id = setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => {
      controller.abort();
      clearInterval(id);
    };
  }, [paused, refreshKey]);

  const eventCount = chain.state === "ok" ? chain.data.total_events : audit.event_count;
  const checkedAt = chain.state === "ok" ? chain.data.checked_at : audit.checked_at;
  const intact = chain.state === "ok" ? chain.data.intact : audit.intact;

  const togglePaused = () => setPaused((p) => !p);
  const refresh = () => setRefreshKey((k) => k + 1);

  const delay = reduced ? "0ms" : "60ms";

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
        <div className="ops-audit-hero-meta">
          <time className="ops-audit-checked" dateTime={checkedAt}>
            {fmtRel(checkedAt)}
          </time>
          <button
            type="button"
            className="ops-audit-pause"
            onClick={togglePaused}
            aria-pressed={paused}
          >
            {paused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}
            <span>{paused ? "Resume updates" : "Pause updates"}</span>
          </button>
        </div>
      </div>

      <div className="ops-audit-verdict">
        <h2>{intact ? "Audit chain intact" : "Audit chain integrity failure"}</h2>
        {!intact && (
          <span>Audit ledger integrity check failed. Escalate immediately.</span>
        )}
      </div>

      <p className="ops-audit-explainer">
        Every event is hashed together with the previous event&apos;s hash. That means
        altering or removing any past event breaks every link that comes after it.
        Each row below shows one link: its own hash, the previous hash it claims,
        and whether the claim checks out.
      </p>

      {chain.state === "loading" && (
        <div className="ops-audit-loading">
          <Skeleton />
        </div>
      )}

      {chain.state === "error" && (
        <div className="ops-audit-empty">
          <span>{chain.message}</span>
          <button type="button" className="ops-audit-retry" onClick={refresh}>
            <RefreshCw size={14} aria-hidden="true" />
            <span>Retry</span>
          </button>
        </div>
      )}

      {chain.state === "ok" && chain.data.links.length === 0 && (
        <div className="ops-audit-empty">
          The audit ledger cannot be read right now.
        </div>
      )}

      {chain.state === "ok" && chain.data.links.length > 0 && (
        <div className="ops-audit-series-list">
          {groupAuditLinks(chain.data.links).map((group) => (
            <section
              key={`${group.claimRef}-${group.traceId}-${group.links[0]?.event_id ?? "group"}`}
              className={`ops-audit-series ${reduced ? "" : "ops-audit-series-enter"}`}
              style={{ "--row-delay": delay } as React.CSSProperties}
            >
              <header className="ops-audit-series-header">
                <span className="ops-audit-series-claim" title={group.claimRef}>
                  Claim <code>{truncateHash(group.claimRef)}</code>
                </span>
                <span className="ops-audit-series-trace" title={group.traceId}>
                  Trace <code>{truncateHash(group.traceId)}</code>
                </span>
                <span className="ops-audit-series-count">
                  {group.links.length} event{group.links.length === 1 ? "" : "s"}
                </span>
              </header>
              <ol className="ops-audit-link-list">
                {group.links.map((link, linkIndex) => (
                  <li
                    key={link.event_id}
                    className={`ops-audit-link ${link.linked ? "" : "ops-audit-link-broken"}`}
                    style={{ "--link-index": linkIndex } as React.CSSProperties}
                  >
                    <div className="ops-audit-link-chain" aria-hidden="true">
                      <span className="ops-audit-link-node" />
                      {linkIndex < group.links.length - 1 && (
                        <span className="ops-audit-link-connector" />
                      )}
                    </div>
                    <div className="ops-audit-link-sequence">#{link.sequence}</div>
                    <div className="ops-audit-link-body">
                      <div className="ops-audit-link-kind">{auditKindLabel(link.kind)}</div>
                      <time className="ops-audit-link-time" dateTime={link.at}>
                        {fmtRel(link.at)}
                      </time>
                    </div>
                    <div className="ops-audit-link-hashes">
                      <span
                        className="ops-audit-hash ops-audit-hash-prev"
                        title={`Previous hash: ${link.prev_hash}`}
                      >
                        <span className="ops-audit-hash-label">previous</span>
                        <code className="ops-audit-hash-value">{truncateHash(link.prev_hash)}</code>
                      </span>
                      <span
                        className="ops-audit-hash ops-audit-hash-self"
                        title={`This link: ${link.chain_hash}`}
                      >
                        <span className="ops-audit-hash-label">this link</span>
                        <code className="ops-audit-hash-value">{truncateHash(link.chain_hash)}</code>
                      </span>
                    </div>
                    <div className="ops-audit-link-status" role="status" aria-label={link.linked ? "Link verifies" : "Link broken"}>
                      {link.linked ? (
                        <Check size={16} aria-hidden="true" />
                      ) : (
                        <AlertTriangle size={16} aria-hidden="true" />
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          ))}
        </div>
      )}
    </section>
  );
}

const SECTION_TITLES: Record<OpsConsoleProps["section"] & string, { title: string; subtitle: string }> = {
  overview: { title: "Operations", subtitle: "Technical reviewer operations overview" },
  metrics: { title: "Metrics", subtitle: "Operational metrics" },
  traces: { title: "Traces", subtitle: "Recent distributed traces" },
  audit: { title: "Audit Integrity", subtitle: "Tamper-evidence audit ledger" },
  activity: { title: "Platform activity", subtitle: "What happened across the platform" },
  roles: { title: "Roles", subtitle: "Platform roles and recent activity" },
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
  const [activityFilters, setActivityFilters] = useState<ActivityFilters>({ role: null, area: null });
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
              activity: null,
              roles: null,
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
        } else if (streamSection === "activity") {
          next.activity = payload as OpsActivityResponse;
        } else if (streamSection === "roles") {
          next.roles = payload as OpsRolesResponse;
        }
        return { state: "ok", data: next };
      });
    },
    [],
  );

  const streamFilters = useMemo(() => {
    if (section !== "activity") return undefined;
    return {
      role: activityFilters.role,
      area: activityFilters.area,
    };
  }, [section, activityFilters.role, activityFilters.area]);

  useEffect(() => {
    if (typeof WebSocket === "undefined") {
      setStreamStatus("offline");
      return;
    }
    const streamSection: OpsStreamSection = section ?? "overview";
    return subscribeOpsStream({
      section: streamSection,
      window,
      filters: streamFilters,
      onSnapshot: (snapshot) => mergeSnapshot(snapshot.section, snapshot.payload),
      onStatus: setStreamStatus,
    });
  }, [section, window, streamFilters, mergeSnapshot]);

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      setBusy(true);
      try {
        const data = await fetchSnapshot(window, section, activityFilters, signal);
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
    [window, section, streamStatus, activityFilters],
  );

  const loadOnce = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const data = await fetchSnapshot(window, section, activityFilters, signal);
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
    [window, section, activityFilters],
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
  const showActivity = !section || section === "activity";
  const showRoles = !section || section === "roles";

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
              <section className="ops-metrics-surface" aria-label="Metrics">
                <div className="ops-metrics-header">
                  <span className="ops-panel-title">Metric categories</span>
                  <WindowSwitch value={window} onChange={setWindow} />
                </div>
                <CategoryGridSkeleton />
              </section>
            )}
            {showTraces && (
              <section className="ops-traces-surface" aria-label="Traces">
                <div className="ops-traces-header">
                  <span className="ops-panel-title">Trace categories</span>
                </div>
                <CategoryGridSkeleton />
              </section>
            )}
            {showAudit && (
              <section className="ops-panel" aria-label="Audit integrity">
                <h2 className="ops-panel-title">Audit integrity</h2>
                <Skeleton />
              </section>
            )}
            {showActivity && (
              <section className="ops-activity-surface" aria-label="Platform activity">
                <div className="ops-activity-header">
                  <span className="ops-panel-title">Platform activity</span>
                  <ActivityFiltersSkeleton />
                </div>
                <Skeleton />
              </section>
            )}
            {showRoles && (
              <section className="ops-roles-surface" aria-label="Roles">
                <div className="ops-roles-grid">
                  {Array.from({ length: 4 }).map((_, i) => (
                    <div key={`role-skel-${i.toString()}`} className="ops-role-card">
                      <div className="ops-skeleton-line" style={{ width: "60%" }} />
                      <div className="ops-skeleton-line" style={{ width: "40%" }} />
                    </div>
                  ))}
                </div>
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
              <MetricsSurface metrics={snap.data.metrics} window={window} reduced={reduced} />
            )}

            {showTraces && snap.data.traces && (
              <TracesSurface traces={snap.data.traces} reduced={reduced} />
            )}

            {showAudit && snap.data.audit && (
              <AuditChainSurface audit={snap.data.audit} reduced={reduced} />
            )}

            {showActivity && snap.data.activity && (
              <ActivitySurface
                activity={snap.data.activity}
                filters={activityFilters}
                onFiltersChange={setActivityFilters}
                reduced={reduced}
              />
            )}

            {showRoles && snap.data.roles && (
              <RolesSurface roles={snap.data.roles} reduced={reduced} />
            )}
          </div>
        )}
      </main>
    </div>
  );
}

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

type MetricSeriesRowProps = {
  series: OpsMetricSeries;
  categoryTotal: number;
  changed: boolean;
  reduced: boolean;
  index: number;
};

function MetricSeriesRow({ series, categoryTotal, changed, reduced, index }: MetricSeriesRowProps) {
  const share = categoryTotal > 0 ? series.value / categoryTotal : 0;
  const heat = metricHeatLevel(series.value, categoryTotal || 1);
  const description = metricLineDescription(series);
  const unit = pluralUnit(series.value, metricCategoryUnit(metricCategory(series.name).key));
  const percent = Math.round(share * 100);
  const delay = reduced ? "0ms" : `${clamp(index, 0, MAX_STAGGER_NODES - 1) * STAGGER_MS}ms`;
  return (
    <li
      className={`ops-metric-series-row ${changed ? "ops-metric-series-row-changed" : ""} ${reduced ? "" : "ops-metric-series-row-enter"}`}
      style={{ "--row-delay": delay } as React.CSSProperties}
      title={description.raw}
    >
      <div className="ops-metric-series-row-main">
        <div className="ops-metric-series-row-text">
          <span className="ops-metric-series-verb">{description.primary}</span>
          {description.secondary && (
            <span className="ops-metric-series-detail">{description.secondary}</span>
          )}
        </div>
      <div className="ops-metric-series-row-value">
        <AnimatedNumber
          value={series.value}
          reduced={reduced}
          className={`ops-metric-series-value ops-signal-heat-${heat}`}
        />{" "}
        <span className="ops-metric-series-unit">{unit}</span>
        <span className="ops-metric-series-share" aria-hidden="true">
          {percent}% of category
        </span>
      </div>
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

function CategoryGridSkeleton() {
  return (
    <ul className="ops-category-grid" aria-hidden="true">
      {Array.from({ length: 4 }).map((_, i) => (
        <li key={`cat-skel-${i.toString()}`} className="ops-category-card ops-category-card-skeleton">
          <div className="ops-skeleton-line" style={{ width: "55%" }} />
          <div className="ops-skeleton-line" style={{ width: "80%" }} />
          <div className="ops-skeleton-line" style={{ width: "40%" }} />
        </li>
      ))}
    </ul>
  );
}

type MetricCategorySummary = {
  category: MetricCategory;
  items: OpsMetricSeries[];
  total: number;
};

function summarizeMetrics(series: readonly OpsMetricSeries[]): MetricCategorySummary[] {
  const map = new Map<string, MetricCategorySummary>();
  for (const cat of METRIC_CATEGORIES) {
    map.set(cat.key, { category: cat, items: [], total: 0 });
  }
  for (const s of series) {
    const cat = metricCategory(s.name);
    const existing = map.get(cat.key);
    if (existing) {
      existing.items.push(s);
      existing.total += s.value;
    }
  }
  return Array.from(map.values());
}

type MetricsSurfaceProps = {
  metrics: OpsMetricsResponse;
  window: OpsWindow;
  reduced: boolean;
};

function MetricsSurface({ metrics, window, reduced }: MetricsSurfaceProps) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const previous = usePreviousMetricValues(metrics.series);
  const changedMap = useMemo(() => {
    const map = new Map<string, boolean>();
    for (const s of metrics.series) {
      const key = seriesKey(s);
      map.set(key, previous.get(key) !== undefined && previous.get(key) !== s.value);
    }
    return map;
  }, [metrics.series, previous]);

  const categories = useMemo(() => summarizeMetrics(metrics.series), [metrics.series]);
  const selected = useMemo(
    () => categories.find((c) => c.category.key === selectedKey) ?? null,
    [categories, selectedKey],
  );

  if (metrics.series.length === 0) {
    return (
      <section className="ops-metrics-surface" aria-label="Metrics">
        <div className="ops-metrics-header">
          <div className="ops-metrics-title">
            <span className="ops-panel-title">Metric categories</span>
            <span className="ops-metrics-meta">
              {metrics.source.name} <StateBadge state={metrics.source.state} />
            </span>
          </div>
          <span className="ops-metrics-updated">
            Updated {fmtRel(metrics.source.last_data_at)}
          </span>
        </div>
        <div className="ops-empty-state">
          <Activity size={24} aria-hidden="true" />
          <p>No metrics available for this window.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="ops-metrics-surface" aria-label="Metrics">
      {selected ? (
        <MetricCategoryDetail
          summary={selected}
          window={window}
          source={metrics.source}
          changedMap={changedMap}
          reduced={reduced}
          onBack={() => setSelectedKey(null)}
        />
      ) : (
        <>
          <div className="ops-metrics-header">
            <div className="ops-metrics-title">
              <span className="ops-panel-title">Metric categories</span>
              <span className="ops-metrics-meta">
                {metrics.source.name} <StateBadge state={metrics.source.state} />
              </span>
            </div>
            <div className="ops-metrics-controls">
              <span className="ops-metrics-updated">
                Updated {fmtRel(metrics.source.last_data_at)}
              </span>
            </div>
          </div>
          <ul className="ops-category-grid" aria-label="Metric categories">
            {categories.map((summary, index) => (
              <li key={summary.category.key}>
                <MetricCategoryCard
                  summary={summary}
                  index={index}
                  reduced={reduced}
                  onSelect={() => setSelectedKey(summary.category.key)}
                />
              </li>
            ))}
          </ul>
          {(() => {
            const nonEmpty = categories.filter((c) => c.items.length > 0).length;
            if (nonEmpty === 0 || nonEmpty > 2) return null;
            return (
              <div className="ops-metrics-sparse">
                <span>
                  Showing {nonEmpty === 1 ? "the only" : `all ${nonEmpty}`} metric
                  categor{nonEmpty === 1 ? "y" : "ies"} with data for this window.
                </span>
              </div>
            );
          })()}
        </>
      )}
    </section>
  );
}

type MetricCategoryCardProps = {
  summary: MetricCategorySummary;
  index: number;
  reduced: boolean;
  onSelect: () => void;
};

function MetricCategoryCard({ summary, index, reduced, onSelect }: MetricCategoryCardProps) {
  const delay = reduced ? "0ms" : `${clamp(index, 0, MAX_STAGGER_NODES - 1) * STAGGER_MS}ms`;
  const empty = summary.items.length === 0;
  return (
    <button
      type="button"
      className={`ops-category-card ${reduced ? "" : "ops-category-card-enter"} ${empty ? "ops-category-card-empty" : ""}`}
      style={{ "--card-delay": delay } as React.CSSProperties}
      onClick={onSelect}
      aria-label={`${summary.category.title}: ${empty ? "no data" : `${summary.items.length} series, ${summary.total.toLocaleString()} total`}`}
    >
      <div className="ops-category-card-top">
        <span className="ops-category-card-count">
          {empty ? "no data" : (
            <>
              <AnimatedNumber value={summary.items.length} reduced={reduced} /> series
            </>
          )}
        </span>
      </div>
      <div className="ops-category-card-body">
        <strong>{summary.category.title}</strong>
        <p>{summary.category.description}</p>
      </div>
      <div className="ops-category-card-foot">
        {empty ? (
          <span className="ops-category-card-placeholder">No samples in window</span>
        ) : (
          <>
            <span className="ops-category-card-figure">
              <AnimatedNumber value={summary.total} reduced={reduced} />{" "}
              {pluralUnit(summary.total, metricCategoryUnit(summary.category.key))}
            </span>
            <span className="ops-category-card-hint">
              view details
              <ChevronRight size={14} aria-hidden="true" />
            </span>
          </>
        )}
      </div>
    </button>
  );
}

type MetricCategoryDetailProps = {
  summary: MetricCategorySummary;
  window: OpsWindow;
  source: import("@/lib/ops-api").OpsSource;
  changedMap: ReadonlyMap<string, boolean>;
  reduced: boolean;
  onBack: () => void;
};

function MetricCategoryDetail({
  summary,
  window,
  source,
  changedMap,
  reduced,
  onBack,
}: MetricCategoryDetailProps) {
  return (
    <div className="ops-category-detail">
      <div className="ops-category-detail-header">
        <button type="button" className="ops-category-detail-back" onClick={onBack} aria-label="Back to metric categories">
          <ChevronLeft size={16} aria-hidden="true" />
          <span>Back to categories</span>
        </button>
        <div className="ops-category-detail-title">
          <span className="ops-panel-title">{summary.category.title}</span>
          <span className="ops-category-detail-meta">{summary.category.description}</span>
        </div>
      </div>

      {summary.items.length === 0 ? (
        <div className="ops-empty-state">
          <Activity size={24} aria-hidden="true" />
          <p>No metrics in this category for this window.</p>
        </div>
      ) : (
        <ul className="ops-metric-series-list" aria-label={`${summary.category.title} series`}>
          {summary.items.map((s, i) => (
            <MetricSeriesRow
              key={seriesKey(s)}
              series={s}
              categoryTotal={summary.total}
              changed={changedMap.get(seriesKey(s)) ?? false}
              reduced={reduced}
              index={i}
            />
          ))}
        </ul>
      )}

      <div className="ops-metric-card-meta">
        <span>window {window}</span>
        <span aria-hidden="true">·</span>
        <span>
          {source.name} {source.state}
        </span>
      </div>
    </div>
  );
}

function medianDuration(traces: readonly OpsTrace[]): number {
  const durations = traces.map((t) => t.duration_ms);
  if (durations.length === 0) return 0;
  const sorted = [...durations].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0
    ? Math.round((sorted[mid - 1] + sorted[mid]) / 2)
    : sorted[mid];
}

function slowestDuration(traces: readonly OpsTrace[]): number {
  return traces.length > 0 ? Math.max(...traces.map((t) => t.duration_ms)) : 0;
}

type TraceCategorySummary = {
  category: TraceCategory;
  traces: OpsTrace[];
};

function summarizeTraces(traces: readonly OpsTrace[]): TraceCategorySummary[] {
  const map = new Map<string, TraceCategorySummary>();
  for (const t of traces) {
    const cat = traceCategory(t.root_name);
    const existing = map.get(cat.key);
    if (existing) {
      existing.traces.push(t);
    } else {
      map.set(cat.key, { category: cat, traces: [t] });
    }
  }
  for (const summary of map.values()) {
    summary.traces.sort((a, b) => {
      const byTime = new Date(b.start_time).getTime() - new Date(a.start_time).getTime();
      if (byTime !== 0) return byTime;
      return a.trace_id.localeCompare(b.trace_id);
    });
  }
  return Array.from(map.values()).sort((a, b) => a.category.title.localeCompare(b.category.title));
}

function allTraceCategories(): TraceCategory[] {
  return [
    { key: "claim_submission", title: "Claim submission", description: "Requests that create or submit new claims." },
    { key: "claims", title: "Claim queries", description: "Requests that read or list claim data." },
    { key: "review", title: "Review decisions", description: "Requests that fetch or record review decisions." },
    { key: "intake", title: "Intake", description: "Document and intake ingestion requests." },
    { key: "auth", title: "Authentication", description: "Sign-in, session, and authentication checks." },
    { key: "ops", title: "Operations & health", description: "Health checks and operations telemetry endpoints." },
    { key: "other", title: "Other requests", description: "Requests that do not belong to a known business category." },
  ];
}

type TracesSurfaceProps = {
  traces: OpsTracesResponse;
  reduced: boolean;
};

function TracesSurface({ traces, reduced }: TracesSurfaceProps) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const byCategory = useMemo(() => summarizeTraces(traces.traces), [traces.traces]);
  const selected = useMemo(
    () => byCategory.find((c) => c.category.key === selectedKey) ?? null,
    [byCategory, selectedKey],
  );

  return (
    <section className="ops-traces-surface" aria-label="Traces">
      {selected ? (
        <TraceCategoryDetail
          summary={selected}
          source={traces.source}
          reduced={reduced}
          onBack={() => setSelectedKey(null)}
        />
      ) : (
        <>
          <div className="ops-traces-header">
            <div className="ops-traces-title">
              <span className="ops-panel-title">Trace categories</span>
              <span className="ops-traces-meta">
                {traces.source.name} <StateBadge state={traces.source.state} />
              </span>
            </div>
            <span className="ops-traces-updated">
              Updated {fmtRel(traces.source.last_data_at)}
            </span>
          </div>
          <ul className="ops-category-grid" aria-label="Trace categories">
            {allTraceCategories().map((category, index) => {
              const summary = byCategory.find((c) => c.category.key === category.key);
              return (
                <li key={category.key}>
                  <TraceCategoryCard
                    category={category}
                    summary={summary}
                    index={index}
                    reduced={reduced}
                    onSelect={() => setSelectedKey(category.key)}
                  />
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

type TraceCategoryCardProps = {
  category: TraceCategory;
  summary: TraceCategorySummary | undefined;
  index: number;
  reduced: boolean;
  onSelect: () => void;
};

function TraceCategoryCard({ category, summary, index, reduced, onSelect }: TraceCategoryCardProps) {
  const delay = reduced ? "0ms" : `${clamp(index, 0, MAX_STAGGER_NODES - 1) * STAGGER_MS}ms`;
  const count = summary?.traces.length ?? 0;
  const median = summary ? medianDuration(summary.traces) : 0;
  const slowest = summary ? slowestDuration(summary.traces) : 0;
  const slow = slowest >= 500;

  return (
    <button
      type="button"
      className={`ops-category-card ${reduced ? "" : "ops-category-card-enter"} ${count === 0 ? "ops-category-card-empty" : ""}`}
      style={{ "--card-delay": delay } as React.CSSProperties}
      onClick={onSelect}
      aria-label={`${category.title}: ${count} ${count === 1 ? "trace" : "traces"}`}
    >
      <div className="ops-category-card-top">
        <span className="ops-category-card-count">
          {count === 0 ? (
            "no traffic"
          ) : (
            <>
              <AnimatedNumber value={count} reduced={reduced} />{" "}
              {count === 1 ? "trace" : "traces"}
            </>
          )}
        </span>
        {slow && <span className="ops-category-card-alert">slow</span>}
      </div>
      <div className="ops-category-card-body">
        <strong>{category.title}</strong>
        <p>{category.description}</p>
      </div>
      <div className="ops-category-card-foot">
        {count > 0 ? (
          <>
            <span className="ops-category-card-figure">
              typical <span>{formatDuration(median)}</span>
            </span>
            <span className="ops-category-card-figure">
              slowest <span>{formatDuration(slowest)}</span>
            </span>
          </>
        ) : (
          <span className="ops-category-card-placeholder">No samples in window</span>
        )}
      </div>
    </button>
  );
}

type TraceCategoryDetailProps = {
  summary: TraceCategorySummary;
  source: import("@/lib/ops-api").OpsSource;
  reduced: boolean;
  onBack: () => void;
};

type OpsSpan = {
  span_id: string;
  parent_span_id: string | null;
  name: string;
  service: string;
  start_offset_ms: number;
  duration_ms: number;
  depth: number;
  status: "ok" | "error";
};

type OpsTraceDetailResponse = {
  source: import("@/lib/ops-api").OpsSource;
  trace_id: string;
  root_name: string;
  duration_ms: number;
  spans: OpsSpan[];
};

async function fetchTraceDetail(traceId: string, signal?: AbortSignal): Promise<OpsTraceDetailResponse> {
  const response = await fetch(`/v1/operations/traces/${encodeURIComponent(traceId)}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      detail = payload.detail ?? payload.message ?? detail;
    } catch {
      // keep the HTTP detail if the body is not JSON
    }
    throw new Error(detail);
  }
  return (await response.json()) as OpsTraceDetailResponse;
}

type AuditChainLink = {
  sequence: number;
  event_id: string;
  at: string;
  kind: string;
  prev_hash: string;
  chain_hash: string;
  claim_ref: string;
  trace_id: string;
  linked: boolean;
};

type AuditChainResponse = {
  intact: boolean;
  checked_at: string;
  total_events: number;
  links: AuditChainLink[];
};

async function fetchAuditChain(limit: number, signal?: AbortSignal): Promise<AuditChainResponse> {
  const response = await fetch(`/v1/operations/audit/chain?limit=${limit}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      detail = payload.detail ?? payload.message ?? detail;
    } catch {
      // keep the HTTP detail if the body is not JSON
    }
    throw new Error(detail);
  }
  return (await response.json()) as AuditChainResponse;
}

const AUDIT_KIND_LABEL: Record<string, string> = {
  claim_received: "Claim received",
  normalized: "Claim was normalised",
  validated: "Claim was validated",
  finding_created: "A finding was raised",
  "finding.suppressed": "A finding was suppressed",
  escalated: "Escalated to a human",
  review_decided: "A reviewer decided",
  override_applied: "An override was applied",
  rule_published: "Rule catalogue updated",
  benchmark_run: "Benchmark run completed",
  llm_called: "A model was consulted",
  handoff: "Handed off",
};

function auditKindLabel(kind: string): string {
  return AUDIT_KIND_LABEL[kind] ?? kind;
}

function truncateHash(hash: string): string {
  if (hash.length <= 18) return hash;
  return `${hash.slice(0, 8)}…${hash.slice(-8)}`;
}

function TraceCategoryDetail({ summary, source, reduced, onBack }: TraceCategoryDetailProps) {
  const [paused, setPaused] = useState(false);
  const [heldSummary, setHeldSummary] = useState(summary);
  const [viewedTraceId, setViewedTraceId] = useState<string | null>(null);

  if (!paused && heldSummary !== summary) {
    setHeldSummary(summary);
  }

  const displaySummary = paused ? heldSummary : summary;
  const durations = displaySummary.traces.map((t) => t.duration_ms);
  const slowest = durations.length > 0 ? Math.max(...durations) : 0;
  const maxDuration = Math.max(1, slowest);

  if (viewedTraceId) {
    return (
      <TraceFlowView
        traceId={viewedTraceId}
        source={source}
        reduced={reduced}
        onBack={() => setViewedTraceId(null)}
      />
    );
  }

  return (
    <div className="ops-category-detail">
      <div className="ops-category-detail-header">
        <button type="button" className="ops-category-detail-back" onClick={onBack} aria-label="Back to trace categories">
          <ChevronLeft size={16} aria-hidden="true" />
          <span>Back to categories</span>
        </button>
        <div className="ops-category-detail-title">
          <span className="ops-panel-title">{displaySummary.category.title}</span>
          <span className="ops-category-detail-meta">{displaySummary.category.description}</span>
        </div>
        {displaySummary.traces.length > 0 && (
          <button
            type="button"
            className={`ops-trace-pause ${paused ? "ops-trace-pause-active" : ""}`}
            onClick={() => setPaused((p) => !p)}
            aria-pressed={paused}
            aria-label={paused ? "Resume live updates" : "Pause live updates"}
          >
            {paused ? <Play size={14} aria-hidden="true" /> : <Pause size={14} aria-hidden="true" />}
            <span>{paused ? "live" : "pause"}</span>
          </button>
        )}
      </div>

      {displaySummary.traces.length === 0 ? (
        <div className="ops-empty-state">
          <Timer size={24} aria-hidden="true" />
          <p>No traffic in this category.</p>
        </div>
      ) : (
        <div className="ops-traces-body">
          <p className="ops-traces-explainer">
            Each row is one request. Duration is the total time from request start to response.
            Typical = median of the category; slowest = longest in the category.
          </p>
          <ul className="ops-trace-rows" aria-label={`${displaySummary.category.title} traces`}>
            {displaySummary.traces.map((t, i) => (
              <TraceRow
                key={t.trace_id}
                trace={t}
                index={i}
                maxDuration={maxDuration}
                slowest={slowest}
                reduced={reduced}
                paused={paused}
                onSelect={() => setViewedTraceId(t.trace_id)}
              />
            ))}
          </ul>
        </div>
      )}

      <div className="ops-metric-card-meta">
        <span>
          {source.name} {source.state}
        </span>
        {paused && <span aria-hidden="true">·</span>}
        {paused && <span>updates paused</span>}
      </div>
    </div>
  );
}

type TraceRowProps = {
  trace: OpsTrace;
  index: number;
  maxDuration: number;
  slowest: number;
  reduced: boolean;
  paused?: boolean;
  onSelect: () => void;
};

type TraceFlowViewProps = {
  traceId: string;
  source: import("@/lib/ops-api").OpsSource;
  reduced: boolean;
  onBack: () => void;
};

function TraceFlowView({ traceId, source, reduced, onBack }: TraceFlowViewProps) {
  const [detail, setDetail] = useState<Loadable<OpsTraceDetailResponse>>({ state: "loading" });
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let ignore = false;
    fetchTraceDetail(traceId, controller.signal)
      .then((data) => {
        if (ignore) return;
        setDetail({ state: "ok", data });
      })
      .catch((err) => {
        if (ignore || controller.signal.aborted) return;
        const message =
          err instanceof Error && err.message.includes("404")
            ? "Trace not found or expired."
            : fetchErrorMessage(err);
        setDetail({ state: "error", message });
      });
    return () => {
      ignore = true;
      controller.abort();
    };
  }, [traceId, retryKey]);

  const retry = () => {
    setDetail({ state: "loading" });
    setRetryKey((k) => k + 1);
  };

  return (
    <div className="ops-category-detail">
      <div className="ops-category-detail-header">
        <button type="button" className="ops-category-detail-back" onClick={onBack} aria-label="Back to trace list">
          <ChevronLeft size={16} aria-hidden="true" />
          <span>Back to traces</span>
        </button>
        <div className="ops-category-detail-title">
          <span className="ops-panel-title">Trace flow</span>
          <span className="ops-category-detail-meta">
            {traceId} · {source.name} <StateBadge state={source.state} />
          </span>
        </div>
      </div>

      {detail.state === "loading" && (
        <div className="ops-empty-state">
          <Activity size={24} aria-hidden="true" className="ops-spin" />
          <p>Loading span details…</p>
        </div>
      )}

      {detail.state === "error" && (
        <div className="ops-error-card">
          <AlertTriangle size={18} aria-hidden="true" />
          <span>{detail.message}</span>
          <button type="button" onClick={() => retry()}>
            Retry
          </button>
        </div>
      )}

      {detail.state === "ok" && <TraceFlowContent detail={detail.data} reduced={reduced} />}
    </div>
  );
}

function TraceFlowContent({ detail, reduced }: { detail: OpsTraceDetailResponse; reduced: boolean }) {
  const totalMs = Math.max(1, detail.duration_ms);
  const unavailable = detail.source.state !== "healthy";
  const notFound = detail.spans.length === 0 && !unavailable;

  if (unavailable) {
    return (
      <div className="ops-empty-state">
        <AlertTriangle size={24} aria-hidden="true" />
        <p>Tempo is currently unavailable — span details cannot be loaded.</p>
      </div>
    );
  }

  if (notFound) {
    return (
      <div className="ops-empty-state">
        <Timer size={24} aria-hidden="true" />
        <p>Trace not found or expired.</p>
      </div>
    );
  }

  return (
    <div className="ops-trace-flow">
      <div className="ops-trace-flow-header">
        <div className="ops-trace-flow-title">
          <span>{traceTitle(detail.root_name)}</span>
          <span className="ops-trace-flow-route" title={detail.root_name}>
            {detail.root_name}
          </span>
        </div>
        <div className="ops-trace-flow-figures">
          <span className="ops-trace-flow-figure">
            total <strong>{formatDuration(detail.duration_ms)}</strong>
          </span>
          <span className="ops-trace-flow-figure">
            spans <strong>{detail.spans.length.toLocaleString()}</strong>
          </span>
        </div>
      </div>

      <p className="ops-trace-flow-explainer">
        Each row is a span — one step inside the request. The left edge is when it started;
        the width is how long it took. Nested rows are children of the span above them.
      </p>

      <ul className="ops-trace-flow-timeline" aria-label={`Spans for trace ${detail.trace_id}`}>
        {detail.spans.map((span, index) => {
          const left = (span.start_offset_ms / totalMs) * 100;
          const width = (span.duration_ms / totalMs) * 100;
          const clampedLeft = clamp(left, 0, 100);
          const clampedWidth = clamp(width, 0.2, 100 - clampedLeft);
          const delay = reduced ? "0ms" : `${clamp(index, 0, MAX_STAGGER_NODES - 1) * STAGGER_MS}ms`;
          return (
            <li
              key={span.span_id}
              className={`ops-trace-flow-row ${reduced ? "" : "ops-trace-flow-row-enter"}`}
              style={{
                "--row-delay": delay,
                paddingLeft: `${12 + span.depth * 18}px`,
              } as React.CSSProperties}
              title={`span ${span.span_id}${span.parent_span_id ? ` · parent ${span.parent_span_id}` : ""}`}
            >
              <div className="ops-trace-flow-row-label">
                <span className="ops-trace-flow-row-name">{span.name}</span>
                <span className="ops-trace-flow-row-service">{span.service}</span>
              </div>
              <div className="ops-trace-flow-row-track" aria-hidden="true">
                <div
                  className={`ops-trace-flow-row-bar ${span.status === "error" ? "ops-trace-flow-row-bar-error" : ""}`}
                  style={{ left: `${clampedLeft}%`, width: `${clampedWidth}%` }}
                />
              </div>
              <span className="ops-trace-flow-row-duration">{formatDuration(span.duration_ms)}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function TraceRow({ trace, index, maxDuration, slowest, reduced, paused, onSelect }: TraceRowProps) {
  const title = traceTitle(trace.root_name);
  const latency = traceLatencyClass(trace.duration_ms);
  const isSlowest = trace.duration_ms === slowest && slowest > 0;
  const scale = trace.duration_ms / maxDuration;
  const staggerIndex = clamp(index, 0, MAX_STAGGER_NODES - 1);
  const delay = reduced ? "0ms" : `${staggerIndex * 25}ms`;

  return (
    <li>
      <button
        type="button"
        className={`ops-trace-row ${isSlowest ? "ops-trace-row-slowest" : ""} ${reduced ? "" : "ops-trace-row-enter"} ${paused ? "ops-trace-row-paused" : ""}`}
        style={{ "--row-delay": delay } as React.CSSProperties}
        onClick={onSelect}
        aria-label={`Trace ${trace.trace_id}: ${trace.root_name} in ${trace.service}, ${formatDuration(trace.duration_ms)}${isSlowest ? " (slowest)" : ""}. Open span flow.`}
      >
        <div className="ops-trace-gutter">
          <span className="ops-trace-gutter-title" title={title}>
            {title}
          </span>
          <span className="ops-trace-gutter-meta">
            <span className="ops-trace-gutter-route" title={trace.root_name}>
              {trace.root_name}
            </span>
            <span className="ops-trace-gutter-service" title={trace.service}>
              {trace.service}
            </span>
          </span>
        </div>
        <div className="ops-trace-track" aria-hidden="true">
          <div
            className={`ops-trace-bar ops-trace-bar-${latency} ${reduced || paused ? "" : "ops-trace-bar-grow"}`}
            style={{
              "--bar-scale": String(scale),
              "--bar-delay": delay,
            } as React.CSSProperties}
          />
        </div>
        <div className="ops-trace-value">
          <span className="ops-trace-duration">
            {formatDuration(trace.duration_ms)}
          </span>
          <span className="ops-trace-duration-label">
            {isSlowest ? "slowest" : "total time"}
          </span>
        </div>
        <div className="ops-trace-detail">
          <span className="ops-trace-detail-id" title={trace.trace_id}>
            {trace.trace_id}
          </span>
          <span className="ops-trace-detail-start">
            {fmtTime(trace.start_time)}
          </span>
          <span className="ops-trace-detail-service">{trace.service}</span>
          <span className="ops-trace-detail-duration">
            {formatDuration(trace.duration_ms)}
          </span>
          {isSlowest && (
            <span className="ops-trace-slowest-badge">slowest</span>
          )}
        </div>
      </button>
    </li>
  );
}

const AREA_LABELS: Record<OpsActivityArea, string> = {
  claim_submission: "claim",
  review_decision: "review",
  intake: "intake",
};

const ACTION_PHRASES: Record<OpsActivityAction, string> = {
  claim_submitted: "submitted a claim",
  decision_recorded: "recorded a decision",
  document_ingested: "ingested a document",
};

const AREA_OPTIONS: OpsActivityArea[] = ["claim_submission", "review_decision", "intake"];

function areaLabel(area: OpsActivityArea): string {
  return AREA_LABELS[area] ?? area;
}

function activitySentence(entry: OpsActivityEntry): string {
  const phrase = ACTION_PHRASES[entry.action] ?? entry.action;
  return `${entry.actor} ${phrase} on ${entry.reference}`;
}

function roleDisplayName(role: string): string {
  return role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function AreaBadge({ area }: { area: OpsActivityArea }) {
  return <span className="ops-area-badge">{areaLabel(area)}</span>;
}

function OutcomeChip({ outcome }: { outcome: string }) {
  return <span className="ops-outcome-chip">{outcome}</span>;
}

function ActivityFiltersSkeleton() {
  return (
    <div className="ops-activity-filters" aria-hidden="true">
      <div className="ops-activity-filter-skel" />
      <div className="ops-activity-filter-skel" />
    </div>
  );
}

type ActivityFiltersProps = {
  filters: ActivityFilters;
  roleOptions: readonly string[];
  onChange: (filters: ActivityFilters) => void;
};

function ActivityFilters({ filters, roleOptions, onChange }: ActivityFiltersProps) {
  return (
    <div className="ops-activity-filters">
      <fieldset className="ops-activity-filter-group">
        <legend className="ops-sr-only">Filter by area</legend>
        <div className="ops-activity-segments">
          <button
            type="button"
            className={filters.area === null ? "ops-active" : ""}
            onClick={() => onChange({ ...filters, area: null })}
            aria-pressed={filters.area === null}
          >
            all areas
          </button>
          {AREA_OPTIONS.map((area) => (
            <button
              key={area}
              type="button"
              className={filters.area === area ? "ops-active" : ""}
              onClick={() => onChange({ ...filters, area })}
              aria-pressed={filters.area === area}
            >
              {areaLabel(area)}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="ops-activity-filter-group">
        <legend className="ops-sr-only">Filter by role</legend>
        <div className="ops-activity-segments">
          <button
            type="button"
            className={filters.role === null ? "ops-active" : ""}
            onClick={() => onChange({ ...filters, role: null })}
            aria-pressed={filters.role === null}
          >
            all roles
          </button>
          {roleOptions.map((role) => (
            <button
              key={role}
              type="button"
              className={filters.role === role ? "ops-active" : ""}
              onClick={() => onChange({ ...filters, role })}
              aria-pressed={filters.role === role}
            >
              {roleDisplayName(role)}
            </button>
          ))}
        </div>
      </fieldset>
    </div>
  );
}

type ActivitySurfaceProps = {
  activity: OpsActivityResponse;
  filters: ActivityFilters;
  onFiltersChange: (filters: ActivityFilters) => void;
  reduced: boolean;
};

function ActivitySurface({ activity, filters, onFiltersChange, reduced }: ActivitySurfaceProps) {
  const roleOptions = useMemo(() => {
    const set = new Set<string>();
    if (filters.role) set.add(filters.role);
    for (const entry of activity.entries) {
      if (entry.role) set.add(entry.role);
    }
    return Array.from(set).sort();
  }, [activity.entries, filters.role]);

  const empty = activity.entries.length === 0;

  return (
    <section className="ops-activity-surface" aria-label="Platform activity">
      <div className="ops-activity-header">
        <div className="ops-activity-title">
          <span className="ops-panel-title">Platform activity</span>
          <span className="ops-activity-meta">
            <StateBadge state={activity.source.state} /> · {activity.entries.length}{" "}
            {activity.entries.length === 1 ? "entry" : "entries"}
          </span>
        </div>
        <ActivityFilters
          filters={filters}
          roleOptions={roleOptions}
          onChange={onFiltersChange}
        />
      </div>

      {empty ? (
        <div className="ops-empty-state">
          <Activity size={24} aria-hidden="true" />
          <p>No activity for the selected filters.</p>
        </div>
      ) : (
        <ul className="ops-activity-list" aria-label="Activity entries">
          {activity.entries.map((entry, index) => (
            <ActivityRow
              key={`${entry.at}-${entry.actor}-${entry.reference}`}
              entry={entry}
              index={index}
              reduced={reduced}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

type ActivityRowProps = {
  entry: OpsActivityEntry;
  index: number;
  reduced: boolean;
};

function ActivityRow({ entry, index, reduced }: ActivityRowProps) {
  const delay = reduced ? "0ms" : `${clamp(index, 0, MAX_STAGGER_NODES - 1) * STAGGER_MS}ms`;
  const sentence = activitySentence(entry);

  return (
    <li
      className={`ops-activity-row ${reduced ? "" : "ops-activity-row-enter"}`}
      style={{ "--row-delay": delay } as React.CSSProperties}
    >
      <div className="ops-activity-row-main">
        <span className="ops-activity-row-sentence" title={`${sentence} · ${fmtRel(entry.at)}`}>
          {sentence} · {fmtRel(entry.at)}
        </span>
        <span className="ops-activity-row-badges">
          <AreaBadge area={entry.area} />
          <OutcomeChip outcome={entry.outcome} />
        </span>
      </div>
      <div className="ops-activity-row-detail">
        {entry.role !== null ? (
          <span className="ops-activity-row-role">{entry.role}</span>
        ) : (
          <span className="ops-activity-row-role ops-activity-row-role-unknown">unknown role</span>
        )}
        <time className="ops-activity-row-time" dateTime={entry.at} title={entry.at}>
          {fmtTime(entry.at)}
        </time>
      </div>
    </li>
  );
}

type RolesSurfaceProps = {
  roles: OpsRolesResponse;
  reduced: boolean;
};

function RolesSurface({ roles, reduced }: RolesSurfaceProps) {
  const [selectedRole, setSelectedRole] = useState<string | null>(null);

  const selected = useMemo(
    () => roles.roles.find((r) => r.role === selectedRole) ?? null,
    [roles.roles, selectedRole],
  );

  return (
    <section className="ops-roles-surface" aria-label="Roles">
      {selected ? (
        <RoleDetail
          role={selected}
          onBack={() => setSelectedRole(null)}
          reduced={reduced}
        />
      ) : (
        <>
          <div className="ops-roles-header">
            <div className="ops-roles-title">
              <span className="ops-panel-title">Roles</span>
              <span className="ops-roles-meta">
                {roles.roles.length} roles · checked {fmtRel(roles.checked_at)}
              </span>
            </div>
          </div>
          <ul className="ops-roles-grid">
            {roles.roles.map((role, index) => (
              <li key={role.role}>
                <RoleCard
                  role={role}
                  index={index}
                  reduced={reduced}
                  onSelect={() => setSelectedRole(role.role)}
                />
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

type RoleCardProps = {
  role: OpsRole;
  index: number;
  reduced: boolean;
  onSelect: () => void;
};

function RoleCard({ role, index, reduced, onSelect }: RoleCardProps) {
  const delay = reduced ? "0ms" : `${clamp(index, 0, MAX_STAGGER_NODES - 1) * STAGGER_MS}ms`;
  const inactive = !role.last_active_at || role.last_active_at === "0001-01-01T00:00:00Z";

  return (
    <button
      type="button"
      className={`ops-role-card ${reduced ? "" : "ops-role-card-enter"} ${inactive ? "ops-role-card-inactive" : ""}`}
      style={{ "--card-delay": delay } as React.CSSProperties}
      onClick={onSelect}
      aria-label={`${roleDisplayName(role.role)} role, ${role.active_members} active members`}
    >
      <div className="ops-role-card-top">
        <Users size={16} aria-hidden="true" />
        <span className={`ops-role-card-last ${inactive ? "ops-role-card-last-inactive" : ""}`}>
          {inactive ? "inactive" : fmtRel(role.last_active_at)}
        </span>
      </div>
      <div className="ops-role-card-body">
        <strong>{roleDisplayName(role.role)}</strong>
        <div className="ops-role-card-stats">
          <span>{role.active_members} active</span>
          <span aria-hidden="true">·</span>
          <span>{role.recent_actions} actions</span>
        </div>
      </div>
      <div className="ops-role-card-areas">
        {role.areas.length > 0 ? (
          role.areas.map((area) => <AreaBadge key={area} area={area} />)
        ) : (
          <span className="ops-role-card-areas-empty">no areas</span>
        )}
      </div>
    </button>
  );
}

type RoleDetailProps = {
  role: OpsRole;
  onBack: () => void;
  reduced: boolean;
};

function RoleDetail({ role, onBack, reduced }: RoleDetailProps) {
  const [activity, setActivity] = useState<Loadable<OpsActivityResponse>>({ state: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      try {
        const data = await getOpsActivity({ role: role.role, limit: ACTIVITY_LIMIT }, controller.signal);
        if (controller.signal.aborted) return;
        setActivity({ state: "ok", data });
      } catch (err) {
        if (controller.signal.aborted) return;
        setActivity({ state: "error", message: fetchErrorMessage(err) });
      }
    };
    void load();
    return () => controller.abort();
  }, [role.role]);

  return (
    <div className="ops-role-detail">
      <div className="ops-role-detail-header">
        <button
          type="button"
          className="ops-role-detail-back"
          onClick={onBack}
          aria-label="Back to roles"
        >
          <ChevronLeft size={16} aria-hidden="true" />
          <span>Back to roles</span>
        </button>
        <div className="ops-role-detail-title">
          <span className="ops-panel-title">{roleDisplayName(role.role)}</span>
          <span className="ops-role-detail-meta">
            {role.active_members} active members · {role.recent_actions} recent actions
          </span>
        </div>
      </div>

      <div className="ops-role-members">
        <span className="ops-panel-title">Members</span>
        <ul className="ops-role-member-list">
          {role.members.map((email) => (
            <li key={email} className="ops-role-member">
              <code>{email}</code>
            </li>
          ))}
        </ul>
      </div>

      <div className="ops-role-activity">
        <span className="ops-panel-title">Recent activity</span>
        {activity.state === "loading" && <Skeleton />}
        {activity.state === "error" && (
          <div className="ops-error-card">
            <AlertTriangle size={18} aria-hidden="true" />
            <span>{activity.message}</span>
            <button
              type="button"
              onClick={() => {
                setActivity({ state: "loading" });
                void getOpsActivity({ role: role.role, limit: ACTIVITY_LIMIT })
                  .then((data) => setActivity({ state: "ok", data }))
                  .catch((err) => setActivity({ state: "error", message: fetchErrorMessage(err) }));
              }}
            >
              Retry
            </button>
          </div>
        )}
        {activity.state === "ok" && activity.data.entries.length === 0 && (
          <div className="ops-empty-state">
            <Activity size={24} aria-hidden="true" />
            <p>No recent activity for this role.</p>
          </div>
        )}
        {activity.state === "ok" && activity.data.entries.length > 0 && (
          <ul className="ops-activity-list" aria-label={`Activity for ${roleDisplayName(role.role)}`}>
            {activity.data.entries.map((entry, index) => (
              <ActivityRow
                key={`${entry.at}-${entry.actor}-${entry.reference}`}
                entry={entry}
                index={index}
                reduced={reduced}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

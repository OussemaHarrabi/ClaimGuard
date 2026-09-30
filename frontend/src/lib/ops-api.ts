const DEFAULT_REQUEST_TIMEOUT_MS = 30_000;

export type PlatformStatus = "ok" | "degraded";

export type ComponentState = "healthy" | "degraded" | "unknown";

export type SourceState = "healthy" | "degraded" | "stale" | "unknown" | "unavailable";

export type OpsWindow = "5m" | "15m" | "1h";

export type OpsComponent = {
  readonly name: string;
  readonly state: ComponentState;
  readonly detail: string | null;
};

export type OpsSource = {
  readonly name: string;
  readonly state: SourceState;
  readonly last_data_at: string | null;
  readonly detail: string | null;
};

export type OpsVersions = {
  readonly engine_rule_version: string;
  readonly schema_revision: string | null;
  readonly service_name: string;
};

export type OpsOverviewResponse = {
  readonly status: PlatformStatus;
  readonly checked_at: string;
  readonly components: readonly OpsComponent[];
  readonly sources: readonly OpsSource[];
  readonly versions: OpsVersions;
};

export type OpsMetricSeries = {
  readonly name: string;
  readonly labels: Readonly<Record<string, string>>;
  readonly value: number;
};

export type OpsMetricsResponse = {
  readonly source: OpsSource;
  readonly window: OpsWindow;
  readonly series: readonly OpsMetricSeries[];
};

export type OpsTrace = {
  readonly trace_id: string;
  readonly root_name: string;
  readonly service: string;
  readonly start_time: string;
  readonly duration_ms: number;
};

export type OpsTracesResponse = {
  readonly source: OpsSource;
  readonly traces: readonly OpsTrace[];
};

export type OpsAuditResponse = {
  readonly intact: boolean;
  readonly checked_at: string;
  readonly event_count: number;
};

export type OpsActivityArea = "claim_submission" | "review_decision" | "intake";

export type OpsActivityAction = "claim_submitted" | "decision_recorded" | "document_ingested";

export type OpsActivityEntry = {
  readonly at: string;
  readonly role: string | null;
  readonly actor: string;
  readonly area: OpsActivityArea;
  readonly action: OpsActivityAction;
  readonly outcome: string;
  readonly reference: string;
};

export type OpsActivityResponse = {
  readonly source: string;
  readonly role: string | null;
  readonly area: OpsActivityArea | null;
  readonly limit: number;
  readonly entries: readonly OpsActivityEntry[];
};

export type OpsRole = {
  readonly role: string;
  readonly active_members: number;
  readonly members: readonly string[];
  readonly recent_actions: number;
  readonly areas: readonly OpsActivityArea[];
  readonly last_active_at: string;
};

export type OpsRolesResponse = {
  readonly checked_at: string;
  readonly roles: readonly OpsRole[];
};

export type OpsFetchError = {
  readonly kind: "error";
  readonly message: string;
};

export type OpsResult<T> = { readonly kind: "ok"; readonly data: T } | OpsFetchError;

export function isOpsResultError<T>(result: OpsResult<T>): result is OpsFetchError {
  return result.kind === "error";
}

export function isOpsResultOk<T>(result: OpsResult<T>): result is { kind: "ok"; data: T } {
  return result.kind === "ok";
}

async function responseJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      detail = payload.detail ?? payload.message ?? detail;
    } catch {
      // Keep the HTTP status detail if the body is not JSON.
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

async function fetchOps<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    cache: "no-store",
    signal: signal ?? AbortSignal.timeout(DEFAULT_REQUEST_TIMEOUT_MS),
  });
  return responseJson<T>(response);
}

export async function getOpsOverview(signal?: AbortSignal): Promise<OpsOverviewResponse> {
  return fetchOps<OpsOverviewResponse>("/v1/operations/overview", signal);
}

export async function getOpsMetrics(
  window: OpsWindow,
  signal?: AbortSignal,
): Promise<OpsMetricsResponse> {
  return fetchOps<OpsMetricsResponse>(`/v1/operations/metrics?window=${window}`, signal);
}

export async function getOpsTraces(
  limit: number,
  signal?: AbortSignal,
): Promise<OpsTracesResponse> {
  const clamped = Math.min(100, Math.max(1, Math.floor(limit)));
  return fetchOps<OpsTracesResponse>(`/v1/operations/traces?limit=${clamped}`, signal);
}

export async function getOpsAudit(signal?: AbortSignal): Promise<OpsAuditResponse> {
  return fetchOps<OpsAuditResponse>("/v1/operations/audit", signal);
}

export async function getOpsActivity(
  filters: { role?: string | null; area?: OpsActivityArea | null; limit?: number } = {},
  signal?: AbortSignal,
): Promise<OpsActivityResponse> {
  const params = new URLSearchParams();
  if (filters.role) params.set("role", filters.role);
  if (filters.area) params.set("area", filters.area);
  if (filters.limit !== undefined && filters.limit > 0) params.set("limit", String(filters.limit));
  const query = params.toString();
  return fetchOps<OpsActivityResponse>(`/v1/operations/activity${query ? `?${query}` : ""}`, signal);
}

export async function getOpsRoles(signal?: AbortSignal): Promise<OpsRolesResponse> {
  return fetchOps<OpsRolesResponse>("/v1/operations/roles", signal);
}

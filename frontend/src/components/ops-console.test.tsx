import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MockWebSocket } from "@/lib/ops-stream-mock";
import {
  getOpsAudit,
  getOpsMetrics,
  getOpsOverview,
  getOpsTraces,
  type OpsAuditResponse,
  type OpsMetricsResponse,
  type OpsOverviewResponse,
  type OpsSource,
  type OpsTracesResponse,
} from "@/lib/ops-api";

import { OpsConsole } from "./ops-console";

vi.mock("@/lib/ops-api", () => ({
  getOpsOverview: vi.fn(),
  getOpsMetrics: vi.fn(),
  getOpsTraces: vi.fn(),
  getOpsAudit: vi.fn(),
}));

const overviewMock = vi.mocked(getOpsOverview);
const metricsMock = vi.mocked(getOpsMetrics);
const tracesMock = vi.mocked(getOpsTraces);
const auditMock = vi.mocked(getOpsAudit);

const CHECKED_AT = "2026-09-29T10:00:00Z";

const healthySource = (name: string): OpsSource => ({
  name,
  state: "healthy",
  last_data_at: CHECKED_AT,
  detail: `${name} reachable`,
});

const makeOverview = (overrides: Partial<OpsOverviewResponse> = {}): OpsOverviewResponse => ({
  status: "ok",
  checked_at: CHECKED_AT,
  components: [
    { name: "api", state: "healthy", detail: "Responding" },
    { name: "database", state: "healthy", detail: "Connected" },
    { name: "rules", state: "healthy", detail: "Catalogue loaded" },
  ],
  sources: [healthySource("prometheus"), healthySource("tempo")],
  versions: {
    engine_rule_version: "1.0.0",
    schema_revision: "0001",
    service_name: "claimguard-api",
  },
  ...overrides,
});

const makeMetrics = (overrides: Partial<OpsMetricsResponse> = {}): OpsMetricsResponse => ({
  source: healthySource("prometheus"),
  window: "5m",
  series: [{ name: "http_requests_total", labels: { route: "/v1/claims" }, value: 42 }],
  ...overrides,
});

const makeTraces = (overrides: Partial<OpsTracesResponse> = {}): OpsTracesResponse => ({
  source: healthySource("tempo"),
  traces: [
    {
      trace_id: "trace-1",
      root_name: "GET /v1/claims",
      service: "api",
      start_time: CHECKED_AT,
      duration_ms: 120,
    },
  ],
  ...overrides,
});

const makeAudit = (overrides: Partial<OpsAuditResponse> = {}): OpsAuditResponse => ({
  intact: true,
  checked_at: CHECKED_AT,
  event_count: 128,
  ...overrides,
});

function mockSnapshot(
  snapshot: {
    overview?: OpsOverviewResponse;
    metrics?: OpsMetricsResponse;
    traces?: OpsTracesResponse;
    audit?: OpsAuditResponse;
  } = {},
): void {
  overviewMock.mockResolvedValue(snapshot.overview ?? makeOverview());
  metricsMock.mockResolvedValue(snapshot.metrics ?? makeMetrics());
  tracesMock.mockResolvedValue(snapshot.traces ?? makeTraces());
  auditMock.mockResolvedValue(snapshot.audit ?? makeAudit());
}

beforeEach(() => {
  vi.resetAllMocks();
  MockWebSocket.lastInstance = null;
  vi.stubGlobal("WebSocket", MockWebSocket);
});

describe("OpsConsole", () => {
  it("renders the platform verdict, component cards, and source cards for a healthy overview", async () => {
    mockSnapshot();
    render(<OpsConsole />);

    expect(await screen.findByText("Platform ok")).toBeInTheDocument();

    const components = within(screen.getByLabelText("Components"));
    expect(components.getByText("api")).toBeInTheDocument();
    expect(components.getByText("database")).toBeInTheDocument();
    expect(components.getByText("rules")).toBeInTheDocument();

    const sources = within(screen.getByLabelText("Sources"));
    expect(sources.getByText("prometheus")).toBeInTheDocument();
    expect(sources.getByText("tempo")).toBeInTheDocument();
  });

  it("distinguishes an unavailable source from a stale source", async () => {
    mockSnapshot({
      overview: makeOverview({
        status: "degraded",
        sources: [
          { name: "prometheus", state: "stale", last_data_at: CHECKED_AT, detail: "No recent scrape" },
          { name: "tempo", state: "unavailable", last_data_at: null, detail: "Endpoint down" },
        ],
      }),
    });
    render(<OpsConsole />);

    expect(await screen.findByText("Platform degraded")).toBeInTheDocument();

    const sources = within(screen.getByLabelText("Sources"));
    expect(sources.getByText("stale")).toBeInTheDocument();
    expect(sources.getByText("unavailable")).toBeInTheDocument();
  });

  it("renders empty states when there are no metrics or traces", async () => {
    mockSnapshot({ metrics: makeMetrics({ series: [] }), traces: makeTraces({ traces: [] }) });
    render(<OpsConsole />);

    expect(await screen.findByText("No metrics available for this window.")).toBeInTheDocument();
    expect(await screen.findByText("No recent traces.")).toBeInTheDocument();
  });

  it("shows the error state with Retry and recovers on a successful refetch", async () => {
    overviewMock.mockRejectedValueOnce(new Error("operations backend down"));
    metricsMock.mockRejectedValueOnce(new Error("operations backend down"));
    tracesMock.mockRejectedValueOnce(new Error("operations backend down"));
    auditMock.mockRejectedValueOnce(new Error("operations backend down"));
    mockSnapshot();

    render(<OpsConsole />);

    expect(await screen.findByText("operations backend down")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Platform ok")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("reflects degradation in the verdict and never renders an all-good state", async () => {
    mockSnapshot({
      overview: makeOverview({
        status: "degraded",
        sources: [
          healthySource("prometheus"),
          { name: "tempo", state: "unavailable", last_data_at: null, detail: "Down" },
        ],
      }),
    });
    render(<OpsConsole />);

    expect(await screen.findByText("Platform degraded")).toBeInTheDocument();
    expect(screen.queryByText("Platform ok")).not.toBeInTheDocument();
  });

  it("renders the integrity-failure banner when the audit chain is broken", async () => {
    mockSnapshot({ audit: makeAudit({ intact: false }) });
    render(<OpsConsole />);

    expect(await screen.findByText("Audit chain integrity failure")).toBeInTheDocument();
    expect(
      screen.getByText("Audit ledger integrity check failed. Escalate immediately."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Audit chain intact")).not.toBeInTheDocument();
  });

  it("updates rendered data when a stream snapshot arrives", async () => {
    mockSnapshot();
    render(<OpsConsole />);

    expect(await screen.findByText("Platform ok")).toBeInTheDocument();

    const ws = MockWebSocket.lastInstance;
    ws?.simulateOpen();
    ws?.simulateMessage({
      type: "snapshot",
      section: "overview",
      at: "2026-09-29T10:05:00Z",
      payload: makeOverview({
        status: "degraded",
        sources: [
          healthySource("prometheus"),
          { name: "tempo", state: "unavailable", last_data_at: null, detail: "Down" },
        ],
      }),
    });

    expect(await screen.findByText("Platform degraded")).toBeInTheDocument();
    expect(screen.queryByText("Platform ok")).not.toBeInTheDocument();
  });

  it("does not disturb state on ping frames", async () => {
    mockSnapshot();
    render(<OpsConsole />);

    expect(await screen.findByText("Platform ok")).toBeInTheDocument();

    const ws = MockWebSocket.lastInstance;
    ws?.simulateOpen();
    ws?.simulateMessage({ type: "ping", at: "2026-09-29T10:00:01Z" });

    await waitFor(() => {
      expect(screen.getByText("Platform ok")).toBeInTheDocument();
    });
  });

  it("reports live when the socket opens and reconnecting/offline when it closes", async () => {
    mockSnapshot();
    render(<OpsConsole />);

    const indicator = await screen.findByLabelText("Stream status");
    expect(indicator.textContent).toBe("connecting");

    const first = MockWebSocket.lastInstance;
    first?.simulateOpen();
    await waitFor(() => expect(indicator.textContent).toBe("live"));

    first?.simulateClose(1006);
    await waitFor(() => expect(indicator.textContent).not.toBe("live"));
  });

  it("recovers to live after a reconnect", async () => {
    mockSnapshot();
    render(<OpsConsole />);

    const indicator = await screen.findByLabelText("Stream status");
    const first = MockWebSocket.lastInstance;
    first?.simulateOpen();
    await waitFor(() => expect(indicator.textContent).toBe("live"));

    first?.simulateClose(1006);
    await waitFor(() => expect(indicator.textContent).toBe("reconnecting"));

    // Wait for the first reconnect attempt (1 s + small buffer).
    await new Promise((resolve) => setTimeout(resolve, 1_100));

    const second = MockWebSocket.lastInstance;
    expect(second).not.toBe(first);
    second?.simulateOpen();
    await waitFor(() => expect(indicator.textContent).toBe("live"));
  });

  it("still renders data via fallback fetch when the socket never connects", async () => {
    mockSnapshot();
    render(<OpsConsole />);

    expect(await screen.findByText("Platform ok")).toBeInTheDocument();
    expect(MockWebSocket.lastInstance?.readyState).toBe(0);
  });
});

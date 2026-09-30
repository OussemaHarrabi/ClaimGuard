import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { MockWebSocket } from "@/lib/ops-stream-mock";
import {
  getOpsActivity,
  getOpsAudit,
  getOpsMetrics,
  getOpsOverview,
  getOpsRoles,
  getOpsTraces,
  type OpsActivityResponse,
  type OpsAuditResponse,
  type OpsMetricsResponse,
  type OpsOverviewResponse,
  type OpsRolesResponse,
  type OpsSource,
  type OpsTracesResponse,
} from "@/lib/ops-api";

import { OpsConsole } from "./ops-console";

vi.mock("@/lib/ops-api", () => ({
  getOpsOverview: vi.fn(),
  getOpsMetrics: vi.fn(),
  getOpsTraces: vi.fn(),
  getOpsAudit: vi.fn(),
  getOpsActivity: vi.fn(),
  getOpsRoles: vi.fn(),
}));

const overviewMock = vi.mocked(getOpsOverview);
const metricsMock = vi.mocked(getOpsMetrics);
const tracesMock = vi.mocked(getOpsTraces);
const auditMock = vi.mocked(getOpsAudit);
const activityMock = vi.mocked(getOpsActivity);
const rolesMock = vi.mocked(getOpsRoles);

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

const makeActivity = (overrides: Partial<OpsActivityResponse> = {}): OpsActivityResponse => ({
  source: { state: "healthy", last_data_at: CHECKED_AT, detail: null },
  role: null,
  area: null,
  limit: 50,
  entries: [
    {
      at: CHECKED_AT,
      role: "rcm_reviewer",
      actor: "reviewer.local@example.test",
      area: "review_decision",
      action: "decision_recorded",
      outcome: "resolved",
      reference: "run-ab12cd34",
    },
  ],
  ...overrides,
});

const makeRoles = (overrides: Partial<OpsRolesResponse> = {}): OpsRolesResponse => ({
  checked_at: CHECKED_AT,
  roles: [
    {
      role: "rcm_reviewer",
      active_members: 2,
      members: ["reviewer.local@example.test"],
      recent_actions: 12,
      areas: ["claim_submission", "review_decision"],
      last_active_at: CHECKED_AT,
    },
  ],
  ...overrides,
});

function mockSnapshot(
  snapshot: {
    overview?: OpsOverviewResponse;
    metrics?: OpsMetricsResponse;
    traces?: OpsTracesResponse;
    audit?: OpsAuditResponse;
    activity?: OpsActivityResponse;
    roles?: OpsRolesResponse;
  } = {},
): void {
  overviewMock.mockResolvedValue(snapshot.overview ?? makeOverview());
  metricsMock.mockResolvedValue(snapshot.metrics ?? makeMetrics());
  tracesMock.mockResolvedValue(snapshot.traces ?? makeTraces());
  auditMock.mockResolvedValue(snapshot.audit ?? makeAudit());
  activityMock.mockResolvedValue(snapshot.activity ?? makeActivity());
  rolesMock.mockResolvedValue(snapshot.roles ?? makeRoles());
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
    expect(await screen.findByText("Trace categories")).toBeInTheDocument();
    expect(screen.getAllByText("no traffic").length).toBeGreaterThan(0);
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

  it("still paints when the socket goes live before the first fetch resolves", async () => {
    // Opening Metrics/Traces/Audit used to show nothing until a manual Refresh:
    // the socket reported `live` almost immediately, which aborted the in-flight
    // first fetch, and the stream's first snapshot for a non-overview section was
    // discarded because `overview` (the verdict) was not in state yet.
    mockSnapshot();
    render(<OpsConsole section="traces" variant="embedded" />);

    MockWebSocket.lastInstance?.simulateOpen();

    const traceCard = await screen.findByRole("button", { name: "Claim queries: 1 trace" });
    expect(traceCard).toBeInTheDocument();
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

  it("renders metric category cards and drills into a category's series", async () => {
    mockSnapshot({
      metrics: makeMetrics({
        series: [
          { name: "http_requests_total", labels: { route: "/v1/claims" }, value: 42 },
          { name: "http_request_duration_seconds", labels: { route: "/v1/claims" }, value: 120 },
        ],
      }),
    });
    render(<OpsConsole section="metrics" variant="embedded" />);

    expect(screen.getByText("Metric categories")).toBeInTheDocument();
    const httpCard = await screen.findByRole("button", { name: /HTTP requests:/i });
    expect(httpCard).toBeInTheDocument();

    fireEvent.click(httpCard);
    expect(await screen.findByText("Back to categories")).toBeInTheDocument();
    expect(screen.getByText("http_requests_total")).toBeInTheDocument();
  });

  it("renders trace category cards and drills into a category's traces", async () => {
    mockSnapshot();
    render(<OpsConsole section="traces" variant="embedded" />);

    const claimCard = await screen.findByRole("button", { name: "Claim queries: 1 trace" });
    expect(claimCard).toBeInTheDocument();
    fireEvent.click(claimCard);

    expect(await screen.findByText("Back to categories")).toBeInTheDocument();
    expect(screen.getByText("GET /v1/claims")).toBeInTheDocument();
  });

  it("renders the activity feed with sentence rows, area badge, and outcome chip", async () => {
    mockSnapshot({
      activity: makeActivity({
        entries: [
          {
            at: CHECKED_AT,
            role: "rcm_reviewer",
            actor: "reviewer.local@example.test",
            area: "review_decision",
            action: "decision_recorded",
            outcome: "resolved",
            reference: "run-ab12cd34",
          },
        ],
      }),
    });
    render(<OpsConsole section="activity" variant="embedded" />);

    expect(await screen.findByText(/reviewer.local@example.test recorded a decision on run-ab12cd34/)).toBeInTheDocument();
    const row = screen.getByText(/reviewer.local@example.test recorded a decision/).closest("li");
    expect(row).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("review")).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText("resolved")).toBeInTheDocument();
  });

  // Regression: the activity endpoint returns `source` as an object {state,last_data_at,detail}, but the
  // client typed it as a string and rendered it directly. React threw "objects are not valid as a React
  // child", which took the whole page down behind an error boundary. The fixture used to mock a string,
  // so it agreed with the wrong type and every test passed. Render the real wire shape instead.
  it("renders the activity source from the real object shape without crashing", async () => {
    mockSnapshot({
      activity: makeActivity({
        source: { state: "degraded", last_data_at: CHECKED_AT, detail: "collector lagging" },
      }),
    });
    render(<OpsConsole section="activity" variant="embedded" />);

    // The badge proves the object `source` rendered as text rather than as an object.
    expect(await screen.findByText("degraded")).toBeInTheDocument();
    // And the source meta line exists at all — it never rendered while the page was crashing.
    const meta = screen.getByLabelText("Platform activity").querySelector(".ops-activity-meta");
    expect(meta?.textContent).toMatch(/entr(y|ies)/);
  });

  it("renders the roles grid and drills into a role's members and activity", async () => {
    mockSnapshot({
      roles: makeRoles({
        roles: [
          {
            role: "rcm_reviewer",
            active_members: 1,
            members: ["reviewer.local@example.test"],
            recent_actions: 5,
            areas: ["claim_submission", "review_decision"],
            last_active_at: CHECKED_AT,
          },
        ],
      }),
      activity: makeActivity({
        role: "rcm_reviewer",
        entries: [
          {
            at: CHECKED_AT,
            role: "rcm_reviewer",
            actor: "reviewer.local@example.test",
            area: "review_decision",
            action: "decision_recorded",
            outcome: "resolved",
            reference: "run-ab12cd34",
          },
        ],
      }),
    });
    render(<OpsConsole section="roles" variant="embedded" />);

    expect(await screen.findByText("Rcm Reviewer")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Rcm Reviewer role/i }));

    expect(await screen.findByText("reviewer.local@example.test")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to roles" })).toBeInTheDocument();
  });
});

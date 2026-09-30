import type {
  OpsAuditResponse,
  OpsMetricsResponse,
  OpsOverviewResponse,
  OpsTracesResponse,
  OpsWindow,
} from "./ops-api";

export type OpsStreamSection = "overview" | "metrics" | "traces" | "audit";

export type OpsStreamStatus = "connecting" | "live" | "reconnecting" | "offline";

export type OpsStreamSnapshot =
  | { readonly section: "overview"; readonly payload: OpsOverviewResponse }
  | { readonly section: "metrics"; readonly payload: OpsMetricsResponse }
  | { readonly section: "traces"; readonly payload: OpsTracesResponse }
  | { readonly section: "audit"; readonly payload: OpsAuditResponse };

type SnapshotFrame = {
  readonly type: "snapshot";
  readonly section: OpsStreamSection;
  readonly at: string;
  readonly payload: unknown;
};

type PingFrame = {
  readonly type: "ping";
  readonly at: string;
};

type ServerFrame = SnapshotFrame | PingFrame;

const DEFAULT_STREAM_URL = "ws://127.0.0.1:8000/v1/operations/stream";
const STREAM_PORT = "8000";
const STREAM_PATH = "/v1/operations/stream";
const MIN_RECONNECT_MS = 1_000;
const MAX_RECONNECT_MS = 15_000;
const BACKOFF_MULTIPLIER = 2;
const OFFLINE_AFTER_ATTEMPTS = 5;

function getStreamUrl(): string {
  const configured =
    typeof process !== "undefined" ? process.env.NEXT_PUBLIC_OPS_STREAM_URL : undefined;
  if (configured) return upgradeToSecure(configured);

  // Default to the SAME HOST the page is served from, not a hardcoded address.
  // The session cookie is bound to that host, and browsers do not share cookies
  // between `localhost` and `127.0.0.1` — connecting across the two would send
  // no cookie at all and the server would close the socket with 4401.
  if (typeof window !== "undefined" && window.location.hostname) {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    return `${scheme}://${window.location.hostname}:${STREAM_PORT}${STREAM_PATH}`;
  }

  return DEFAULT_STREAM_URL;
}

function upgradeToSecure(url: string): string {
  if (
    typeof window !== "undefined" &&
    window.location.protocol === "https:" &&
    url.startsWith("ws:")
  ) {
    return `wss${url.slice(2)}`;
  }
  return url;
}

function buildUrl(section: OpsStreamSection, window: OpsWindow): string {
  const base = getStreamUrl();
  const separator = base.includes("?") ? "&" : "?";
  return `${base}${separator}section=${encodeURIComponent(section)}&window=${encodeURIComponent(window)}`;
}

function isRejectionCloseCode(code: number): boolean {
  // 4401 = no session, 4403 = authenticated but not permitted.
  return code === 4401 || code === 4403;
}

function parseFrame(data: unknown): ServerFrame | null {
  if (typeof data !== "string") return null;
  try {
    const parsed = JSON.parse(data) as unknown;
    if (typeof parsed !== "object" || parsed === null) return null;
    const frame = parsed as { type?: unknown };
    if (frame.type === "snapshot" || frame.type === "ping") {
      return parsed as ServerFrame;
    }
    return null;
  } catch {
    return null;
  }
}

export type SubscribeOpsStreamOptions = {
  readonly section: OpsStreamSection;
  readonly window: OpsWindow;
  readonly onSnapshot: (snapshot: OpsStreamSnapshot) => void;
  readonly onStatus: (status: OpsStreamStatus) => void;
};

export function subscribeOpsStream({
  section,
  window,
  onSnapshot,
  onStatus,
}: SubscribeOpsStreamOptions): () => void {
  if (typeof WebSocket === "undefined") {
    onStatus("offline");
    return () => {};
  }

  let ws: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let attempt = 0;
  let stopped = false;
  let intentionalClose = false;

  const clearReconnectTimer = () => {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const scheduleReconnect = () => {
    if (stopped || ws !== null) return;
    clearReconnectTimer();
    const delay = Math.min(MIN_RECONNECT_MS * BACKOFF_MULTIPLIER ** attempt, MAX_RECONNECT_MS);
    attempt += 1;
    onStatus(attempt > OFFLINE_AFTER_ATTEMPTS ? "offline" : "reconnecting");
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (!stopped) connect();
    }, delay);
  };

  const sendSubscription = () => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ section, window }));
    }
  };

  const connect = () => {
    if (stopped || ws !== null) return;

    onStatus("connecting");
    let url: string;
    try {
      url = buildUrl(section, window);
    } catch {
      onStatus("offline");
      return;
    }

    intentionalClose = false;
    try {
      ws = new WebSocket(url);
    } catch {
      ws = null;
      scheduleReconnect();
      return;
    }

    ws.addEventListener("open", () => {
      if (stopped) {
        ws?.close(1000, "teardown");
        return;
      }
      attempt = 0;
      onStatus("live");
      sendSubscription();
    });

    ws.addEventListener("message", (event) => {
      if (stopped) return;
      const frame = parseFrame(event.data);
      if (!frame) return;
      if (frame.type === "ping") return;
      if (frame.section !== section) return;
      onSnapshot({
        section: frame.section,
        payload: frame.payload,
      } as OpsStreamSnapshot);
    });

    ws.addEventListener("error", () => {
      if (stopped) return;
      onStatus("reconnecting");
    });

    ws.addEventListener("close", (event) => {
      const wasIntentional = intentionalClose;
      ws = null;
      if (stopped) return;
      if (wasIntentional) {
        // An intentional close (e.g. param change) is not an error; just stop.
        return;
      }
      if (isRejectionCloseCode(event.code)) {
        onStatus("offline");
        return;
      }
      scheduleReconnect();
    });
  };

  connect();

  return () => {
    stopped = true;
    clearReconnectTimer();
    if (ws) {
      intentionalClose = true;
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(1000, "unsubscribe");
      }
      ws = null;
    }
  };
}

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MockWebSocket } from "./ops-stream-mock";
import type { OpsWindow } from "./ops-api";
import { subscribeOpsStream, type OpsStreamSection } from "./ops-stream";

describe("subscribeOpsStream", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    MockWebSocket.lastInstance = null;
    vi.stubGlobal("WebSocket", MockWebSocket);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  const subscribe = (
    section: OpsStreamSection = "overview",
    window: OpsWindow = "5m",
  ) => {
    const onSnapshot = vi.fn();
    const onStatus = vi.fn();
    const unsubscribe = subscribeOpsStream({ section, window, onSnapshot, onStatus });
    return { onSnapshot, onStatus, unsubscribe };
  };

  it("reports connecting immediately and opens a socket to the stream endpoint", () => {
    const { onStatus } = subscribe("metrics", "15m");
    expect(onStatus).toHaveBeenLastCalledWith("connecting");
    expect(MockWebSocket.lastInstance).not.toBeNull();
    expect(MockWebSocket.lastInstance?.url).toContain("/v1/operations/stream");
    expect(MockWebSocket.lastInstance?.url).toContain("section=metrics");
    expect(MockWebSocket.lastInstance?.url).toContain("window=15m");
  });

  it("sends a subscription message after the socket opens", () => {
    subscribe("traces", "1h");
    const ws = MockWebSocket.lastInstance;
    expect(ws?.sent).toHaveLength(0);
    ws?.simulateOpen();
    expect(ws?.sent).toHaveLength(1);
    expect(JSON.parse(ws?.sent[0] ?? "{}")).toEqual({ section: "traces", window: "1h" });
  });

  it("delivers snapshot payloads and ignores pings", () => {
    const { onSnapshot } = subscribe("audit", "5m");
    const ws = MockWebSocket.lastInstance;
    ws?.simulateOpen();

    const payload = { intact: true, checked_at: "2026-09-30T10:00:00Z", event_count: 42 };
    ws?.simulateMessage({
      type: "snapshot",
      section: "audit",
      at: "2026-09-30T10:00:00Z",
      payload,
    });

    expect(onSnapshot).toHaveBeenCalledTimes(1);
    expect(onSnapshot).toHaveBeenLastCalledWith({ section: "audit", payload });

    ws?.simulateMessage({ type: "ping", at: "2026-09-30T10:00:01Z" });
    expect(onSnapshot).toHaveBeenCalledTimes(1);
  });

  it("ignores snapshots for a different section", () => {
    const { onSnapshot } = subscribe("metrics", "5m");
    const ws = MockWebSocket.lastInstance;
    ws?.simulateOpen();
    ws?.simulateMessage({
      type: "snapshot",
      section: "overview",
      at: "2026-09-30T10:00:00Z",
      payload: { status: "ok" },
    });
    expect(onSnapshot).not.toHaveBeenCalled();
  });

  it("goes reconnecting when the socket closes and recovers to live on reconnect", async () => {
    const { onStatus } = subscribe("overview", "5m");
    const first = MockWebSocket.lastInstance;
    first?.simulateOpen();
    expect(onStatus).toHaveBeenLastCalledWith("live");

    first?.simulateClose(1006);
    expect(onStatus).toHaveBeenLastCalledWith("reconnecting");

    await vi.advanceTimersByTimeAsync(1_100);
    const second = MockWebSocket.lastInstance;
    expect(second).not.toBe(first);
    second?.simulateOpen();
    expect(onStatus).toHaveBeenLastCalledWith("live");
  });

  it("backs off reconnect attempts and eventually reports offline", async () => {
    const { onStatus } = subscribe("overview", "5m");
    const ws = MockWebSocket.lastInstance;
    ws?.simulateOpen();
    ws?.simulateClose(1006);

    for (let i = 0; i < 6; i += 1) {
      await vi.advanceTimersByTimeAsync(16_000);
      MockWebSocket.lastInstance?.simulateClose(1006);
    }

    expect(onStatus).toHaveBeenLastCalledWith("offline");
  });

  it("stops reconnecting after a rejection close code", () => {
    const { onStatus, unsubscribe } = subscribe("overview", "5m");
    const ws = MockWebSocket.lastInstance;
    ws?.simulateOpen();
    ws?.simulateClose(4403);

    expect(onStatus).toHaveBeenLastCalledWith("offline");

    unsubscribe();
  });

  it("cleans up the socket and timers on unsubscribe", () => {
    const { unsubscribe } = subscribe("overview", "5m");
    const ws = MockWebSocket.lastInstance;
    const closeSpy = vi.spyOn(ws as MockWebSocket, "close");
    unsubscribe();
    expect(closeSpy).toHaveBeenCalled();
    vi.advanceTimersByTime(20_000);
    expect(MockWebSocket.lastInstance).toBe(ws);
  });
});

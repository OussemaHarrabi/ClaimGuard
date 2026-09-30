export type MockWebSocketInstance = {
  url: string;
  readyState: number;
  protocol: string;
  sent: readonly string[];
  simulateOpen: () => void;
  simulateMessage: (payload: unknown) => void;
  simulateClose: (code?: number, reason?: string) => void;
};

export class MockWebSocket {
  static lastInstance: MockWebSocket | null = null;
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState = MockWebSocket.CONNECTING;
  protocol = "";
  sent: string[] = [];

  private listeners = new Map<string, Set<(event: Event) => void>>();

  constructor(url: string) {
    this.url = url;
    MockWebSocket.lastInstance = this;
  }

  addEventListener(type: string, listener: (event: Event) => void) {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: (event: Event) => void) {
    this.listeners.get(type)?.delete(listener);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000, reason = "") {
    this.readyState = MockWebSocket.CLOSED;
    this.dispatch("close", new CloseEvent("close", { code, reason }));
  }

  private dispatch(type: string, event: Event) {
    const set = this.listeners.get(type);
    if (!set) return;
    for (const listener of set) {
      listener(event);
    }
  }

  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.dispatch("open", new Event("open"));
  }

  simulateMessage(payload: unknown) {
    this.dispatch("message", new MessageEvent("message", { data: JSON.stringify(payload) }));
  }

  simulateClose(code = 1006, reason = "") {
    this.close(code, reason);
  }
}

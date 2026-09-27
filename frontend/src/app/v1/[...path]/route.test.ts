/**
 * The /v1 proxy contract, pinned.
 *
 * The origin used to be a `rewrites()` entry, which Next resolves at BUILD time.
 * That meant `CLAIMGUARD_API_ORIGIN` exported when starting the server was
 * silently ignored, the cockpit rendered, and every request 404'd with no
 * explanation. These tests hold the two properties that fixed it:
 *
 *   1. the origin is read PER REQUEST, so changing the variable retargets a
 *      running server without a rebuild; and
 *   2. a wrong or unreachable origin produces a 502 that NAMES the origin, so the
 *      interface can say what is wrong instead of showing an empty queue.
 *
 * They also pin the method filter: the review API exposes GET and POST, and
 * nothing else should be forwarded upstream.
 */

import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GET, POST } from "./route";

const ORIGINAL_ORIGIN = process.env.CLAIMGUARD_API_ORIGIN;

/** A real NextRequest: its own `nextUrl`, `headers` and `text()` are what the handler reads. */
function request(method: string, url = "http://127.0.0.1:3000/v1/queue?include_all=true") {
  return new NextRequest(url, {
    method,
    headers: method === "POST" ? { "content-type": "application/json" } : undefined,
    body: method === "POST" ? JSON.stringify({ claim: { claim_id: "CG-1" } }) : undefined,
  });
}

const context = { params: Promise.resolve({ path: ["runs", "RUN-1", "results"] }) };

function mockFetch(behaviour: (target: string) => Response | Promise<Response>) {
  const calls: Array<{ target: string; method: string; body: unknown }> = [];
  const fake = vi.fn(async (target: string, init: RequestInit = {}) => {
    calls.push({ target, method: init.method ?? "GET", body: init.body });
    return behaviour(target);
  });
  vi.stubGlobal("fetch", fake);
  return calls;
}

describe("the /v1 proxy", () => {
  beforeEach(() => {
    delete process.env.CLAIMGUARD_API_ORIGIN;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    if (ORIGINAL_ORIGIN === undefined) delete process.env.CLAIMGUARD_API_ORIGIN;
    else process.env.CLAIMGUARD_API_ORIGIN = ORIGINAL_ORIGIN;
  });

  it("reads the origin per request, so a running server can be retargeted", async () => {
    const calls = mockFetch(() => new Response("{}", { status: 200, headers: { "content-type": "application/json" } }));

    process.env.CLAIMGUARD_API_ORIGIN = "http://api-old:8000";
    await GET(request("GET"), context);
    process.env.CLAIMGUARD_API_ORIGIN = "http://api-new:9000";
    await GET(request("GET"), context);

    expect(calls.map((call) => new URL(call.target).origin)).toEqual(["http://api-old:8000", "http://api-new:9000"]);
  });

  it("falls back to the documented default when nothing is configured", async () => {
    const calls = mockFetch(() => new Response("{}", { status: 200 }));
    await GET(request("GET"), context);
    expect(new URL(calls[0].target).origin).toBe("http://127.0.0.1:8000");
  });

  it("keeps the path, the query string and the upstream status", async () => {
    const calls = mockFetch(() => new Response('{"ok":true}', { status: 201, headers: { "content-type": "application/json" } }));

    const response = await GET(request("GET"), context);

    expect(calls[0].target).toBe("http://127.0.0.1:8000/v1/runs/RUN-1/results?include_all=true");
    expect(response.status).toBe(201);
    expect(await response.text()).toBe('{"ok":true}');
  });

  it("names the origin when it cannot be reached, instead of failing silently", async () => {
    mockFetch(() => {
      throw new TypeError("fetch failed");
    });
    process.env.CLAIMGUARD_API_ORIGIN = "http://127.0.0.1:5999";

    const response = await GET(request("GET"), context);

    expect(response.status).toBe(502);
    expect(await response.text()).toContain("http://127.0.0.1:5999");
  });

  it("forwards a POST body and does not cache any answer", async () => {
    const calls = mockFetch(() => new Response("{}", { status: 201 }));
    const response = await POST(request("POST"), context);

    expect(calls[0].method).toBe("POST");
    expect(calls[0].body).toContain("CG-1");
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  it("refuses a method the review API does not expose", async () => {
    const calls = mockFetch(() => new Response("{}", { status: 200 }));

    const response = await GET(request("DELETE"), context);

    expect(response.status).toBe(405);
    expect(calls).toHaveLength(0);
  });
});

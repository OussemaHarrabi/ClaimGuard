/**
 * The browser's only path to the review API.
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The cockpit calls `/v1/*` on its own origin, and this handler forwards those
 * calls to the FastAPI service. Keeping them on one origin means no CORS, no
 * API hostname in the browser bundle, and no CORS preflight on every decision.
 *
 * It used to be a `rewrites()` entry in `next.config.ts`, which Next resolves
 * while BUILDING: the API origin was frozen into `.next/routes-manifest.json`.
 * That produced a nasty failure mode. Build without `CLAIMGUARD_API_ORIGIN` and
 * the image or bundle silently targets the default `http://127.0.0.1:8000`;
 * export the variable later, when starting, and it is ignored - the cockpit
 * renders, every request 404s, and nothing says why. Changing which API the app
 * talks to required a rebuild.
 *
 * Reading the variable HERE, per request, makes it what it looks like: a runtime
 * setting, identical under `next dev`, `next start` and the standalone server in
 * the container. Nothing about the API's address is baked into a build.
 *
 * WHAT IT DELIBERATELY DOES NOT DO
 * --------------------------------
 * It forwards only the ClaimGuard session cookie (never arbitrary browser
 * cookies), it caches nothing, and it proxies only the methods the API exposes.
 * A wrong or unreachable origin is reported as
 * a 502 naming the origin, so the failure is legible instead of an empty screen.
 */

import type { NextRequest } from "next/server";

/** Where the review API lives unless the environment says otherwise. */
const DEFAULT_API_ORIGIN = "http://127.0.0.1:8000";

/** How long to wait for the API before reporting it as unreachable. */
const UPSTREAM_TIMEOUT_MS = 30_000;

/** The methods the review API exposes, as a lookup. Anything else is not proxied. */
const PROXIED_METHODS: Record<string, true> = { GET: true, POST: true, HEAD: true };

export const dynamic = "force-dynamic";

function apiOrigin(): string {
  const configured = process.env.CLAIMGUARD_API_ORIGIN?.trim();
  return (configured && configured.length > 0 ? configured : DEFAULT_API_ORIGIN).replace(/\/+$/, "");
}

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });
}

async function proxy(request: NextRequest, path: string[]): Promise<Response> {
  if (!PROXIED_METHODS[request.method]) {
    return json({ detail: `The reviewer API does not accept ${request.method}.` }, 405);
  }
  if (request.method === "POST") {
    const browserOrigin = request.headers.get("origin");
    const publicHost = request.headers.get("host") ?? request.nextUrl.host;
    let sameOrigin = true;
    if (browserOrigin) {
      try {
        const parsed = new URL(browserOrigin);
        sameOrigin = parsed.host === publicHost && parsed.protocol === request.nextUrl.protocol && parsed.pathname === "/" && !parsed.search && !parsed.hash;
      } catch {
        sameOrigin = false;
      }
    }
    if (!sameOrigin || request.headers.get("sec-fetch-site") === "cross-site") {
      return json({ detail: "Cross-origin clinic action denied." }, 403);
    }
  }
  const origin = apiOrigin();
  const target = `${origin}/v1/${path.map(encodeURIComponent).join("/")}${request.nextUrl.search}`;
  const body = request.method === "POST" ? await request.text() : undefined;
  const headers = new Headers({ "content-type": request.headers.get("content-type") ?? "application/json" });
  const session = request.cookies.get("claimguard_session")?.value;
  if (session) headers.set("cookie", `claimguard_session=${session}`);

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch (cause) {
    // The one failure that used to be invisible: name the origin we tried.
    const reason = cause instanceof Error ? cause.message : String(cause);
    return json({ detail: `The review API at ${origin} is unreachable (${reason}).` }, 502);
  }

  const responseHeaders = new Headers({
    "content-type": upstream.headers.get("content-type") ?? "application/json",
    "cache-control": "no-store",
  });
  const loginCookie = upstream.headers.get("set-cookie");
  if (loginCookie?.startsWith("claimguard_session=")) {
    const localHost = ["localhost", "127.0.0.1", "[::1]"].includes(request.nextUrl.hostname);
    const requiresSecure = request.nextUrl.protocol === "https:" || !localHost;
    responseHeaders.set("set-cookie", requiresSecure && !/;\s*Secure(?:;|$)/i.test(loginCookie) ? `${loginCookie}; Secure` : loginCookie);
  }
  return new Response(await upstream.text(), {
    status: upstream.status,
    headers: responseHeaders,
  });
}

type RouteContext = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  return proxy(request, path);
}

export async function POST(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  return proxy(request, path);
}

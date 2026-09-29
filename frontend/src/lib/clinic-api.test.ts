import { afterEach, describe, expect, it, vi } from "vitest";

import { getSession, signIn } from "./clinic-api";

afterEach(() => vi.unstubAllGlobals());

describe("clinic session API", () => {
  it("distinguishes a missing session from an unreachable API", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
    expect(await getSession()).toBeNull();
  });

  it("posts credentials to the live login endpoint and returns the server role", async () => {
    const fetcher = vi.fn(async (_url: string, _init?: RequestInit) => { void _url; void _init; return new Response(JSON.stringify({
      user_id: "user-1", tenant_id: "clinic-a", role: "rcm_reviewer",
    }), { status: 200 }); });
    vi.stubGlobal("fetch", fetcher);

    const session = await signIn("clinic-a", "reviewer@example.test", "strong-password");

    expect(session.role).toBe("rcm_reviewer");
    expect(fetcher.mock.calls[0][0]).toBe("/v1/auth/login");
    expect(fetcher.mock.calls[0][1]?.method).toBe("POST");
  });
});

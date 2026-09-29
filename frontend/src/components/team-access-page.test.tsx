import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { TeamAccessPage } from "./team-access-page";

afterEach(() => vi.unstubAllGlobals());

it("creates a real clinic account and can revoke its membership", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url === "/v1/team?include_inactive=true" && !init) return new Response("[]", { status: 200 });
    if (url === "/v1/team" && init?.method === "POST") return new Response(JSON.stringify({
      user_id: "user-7", email: "rev@example.test", display_name: "Reviewer", role: "rcm_reviewer", active: true,
    }), { status: 201 });
    if (url === "/v1/team/user-7/status") return new Response(JSON.stringify({
      user_id: "user-7", email: "rev@example.test", display_name: "Reviewer", role: "rcm_reviewer", active: false,
    }), { status: 200 });
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<TeamAccessPage />);

  await screen.findByText(/no team members/i);
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "rev@example.test" } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: "correct horse battery staple" } });
  fireEvent.click(screen.getByRole("button", { name: "Create account" }));
  await screen.findByText("rev@example.test");
  fireEvent.click(screen.getByRole("button", { name: "Deactivate rev@example.test" }));
  await waitFor(() => expect(calls.some((call) => call.url === "/v1/team/user-7/status")).toBe(true));
  expect(await screen.findByText("Inactive")).toBeInTheDocument();
});

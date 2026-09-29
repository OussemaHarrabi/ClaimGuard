import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { AssignmentsPage } from "./assignments-page";

afterEach(() => vi.unstubAllGlobals());

it("loads live claims and reviewers, then records an assignment", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/v1/queue?include_all=true") return new Response(JSON.stringify({ claims: [{ claim_id: "CG-17", run_id: "RUN-17", unresolved: 2 }] }), { status: 200 });
    if (url === "/v1/team") return new Response(JSON.stringify([{ user_id: "rev-1", email: "rev@example.test", role: "rcm_reviewer" }]), { status: 200 });
    if (url === "/v1/assignments" && init?.method === "POST") return new Response(JSON.stringify({ claim_id: "CG-17", reviewer_user_id: "rev-1" }), { status: 200 });
    if (url === "/v1/assignments") return new Response("[]", { status: 200 });
    throw new Error(`unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<AssignmentsPage />);

  expect(await screen.findByText("CG-17")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Reviewer for CG-17"), { target: { value: "rev-1" } });
  fireEvent.click(screen.getByRole("button", { name: "Assign CG-17" }));

  await waitFor(() => expect(fetcher).toHaveBeenCalledWith("/v1/assignments", expect.objectContaining({ method: "POST" })));
  expect(await screen.findByText(/assignment saved/i)).toBeInTheDocument();
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { DepartmentsPage } from "./departments-page";

afterEach(() => vi.unstubAllGlobals());

it("creates and deactivates a real clinic department", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url === "/v1/departments" && !init) return new Response("[]", { status: 200 });
    if (url === "/v1/departments" && init?.method === "POST") return new Response(JSON.stringify({ department_id: "dep-1", name: "Dental", active: true }), { status: 201 });
    if (url === "/v1/departments/dep-1/update") return new Response(JSON.stringify({ department_id: "dep-1", name: "Dental", active: false }), { status: 200 });
    throw new Error(`unexpected ${url}`);
  }));
  render(<DepartmentsPage />);
  await screen.findByText(/no departments/i);
  fireEvent.change(screen.getByLabelText("Department name"), { target: { value: "Dental" } });
  fireEvent.click(screen.getByRole("button", { name: "Add department" }));
  await screen.findByText("Dental");
  fireEvent.click(screen.getByRole("button", { name: "Deactivate Dental" }));
  await waitFor(() => expect(calls.some((call) => call.url === "/v1/departments/dep-1/update")).toBe(true));
  expect(await screen.findByText("Inactive")).toBeInTheDocument();
});

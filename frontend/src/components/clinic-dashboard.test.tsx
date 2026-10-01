import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ClinicDashboard } from "./clinic-dashboard";

afterEach(() => vi.unstubAllGlobals());
describe("clinic overview", () => {
  it("uses recorded clinic counts and links assignment work to its real page", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ overview: { claims: 10, assigned_claims: 7, open_requests: 2, open_escalations: 1, intake_pending: 0 }, daily: [{ day: "2026-09-30", runs: 12, claims: 10 }], findings_by_status: [{ status: "FAIL", total: 4 }] })));
    vi.stubGlobal("fetch", fetcher);
    render(<ClinicDashboard />);
    expect(await screen.findByText("3 claims awaiting assignment")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /^awaiting assignment/i })).toHaveAttribute("href", "/workspace/assignments");
    expect(screen.getByLabelText("Issues found results")).toHaveAttribute("value", "4");
    expect(screen.queryByRole("link", { name: /intake awaiting review/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /^open requests/i })).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledWith("/v1/analytics", { cache: "no-store" });
  });
  it("reports an unavailable API without inventing zero counts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 503 })));
    render(<ClinicDashboard />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded");
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
    expect(screen.queryByText("Claims in your clinic")).not.toBeInTheDocument();
  });
});

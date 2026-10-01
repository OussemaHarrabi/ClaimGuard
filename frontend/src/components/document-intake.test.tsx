import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DocumentIntakePage } from "./clinic-workflow-pages";

afterEach(() => vi.unstubAllGlobals());

describe("Document Intake", () => {
  it("offers explicit JSON, five-file CSV and sidecar-checked FHIR paths", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("[]", { status: 200 })));
    render(<DocumentIntakePage />);
    expect(screen.getByRole("combobox", { name: /source format/i })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: /source format/i }), { target: { value: "csv_split" } });
    expect(screen.getByLabelText(/five CSV files/i)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: /source format/i }), { target: { value: "fhir_bundle" } });
    expect(screen.getByLabelText(/FHIR R4 Bundle/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/normalized sidecar/i)).toBeInTheDocument();
    expect(screen.getByText(/does not invent missing values/i)).toBeInTheDocument();
  });

  it("shows the stored source digest beside the draft for manual traceability", async () => {
    const digest = "a".repeat(64);
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
      url === "/v1/intake-jobs" ? [{ job_id: "job-1", filename: "sample.json", status: "needs_review", error_code: null, run_id: null, created_at: "2026-10-01T00:00:00Z" }] :
        { job_id: "job-1", filename: "sample.json", status: "needs_review", error_code: null, run_id: null, created_at: "2026-10-01T00:00:00Z", content_sha256: digest, draft: { claim_id: "TEST-1", lines: [] } },
    ), { status: 200 }))));
    render(<DocumentIntakePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Review draft" }));
    await waitFor(() => expect(screen.getByText(digest)).toBeInTheDocument());
    expect(screen.getByText(/Source package SHA-256/i)).toBeInTheDocument();
  });
});

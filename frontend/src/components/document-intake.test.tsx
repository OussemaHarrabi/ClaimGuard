import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

  it("queues an uploaded package without starting it or opening the draft", async () => {
    const uploaded = { job_id: "job-9", filename: "claim.json", status: "needs_review", error_code: null, run_id: null, created_at: "2026-10-01T10:00:00Z" };
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/v1/intake-jobs" && init?.method === "POST") return Promise.resolve(new Response(JSON.stringify(uploaded), { status: 201 }));
      if (url === "/v1/intake-jobs") return Promise.resolve(new Response(JSON.stringify([uploaded]), { status: 200 }));
      throw new Error(`unexpected request ${init?.method ?? "GET"} ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<DocumentIntakePage />);
    const file = new File([JSON.stringify({ claim_id: "TEST-1" })], "claim.json", { type: "application/json" });
    fireEvent.change(await screen.findByLabelText(/Complete claim JSON file/i), { target: { files: [file] } });
    const upload = await screen.findByRole("button", { name: "Normalize and add to waiting list" });
    await waitFor(() => expect(upload).toBeEnabled());
    (upload.closest("form") as HTMLFormElement).noValidate = true; // jsdom cannot validate a file input handed to it synthetically
    fireEvent.click(upload);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Package received and normalized. It is waiting in the list - press Start check when you are ready."));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/submit"))).toHaveLength(0);
    expect(within(screen.getByRole("heading", { name: "Waiting to be checked (1)" }).closest("section") as HTMLElement).getByText("Waiting to be checked")).toBeInTheDocument();
  });

  it("orders the queue waiting first, then checked, then rejected, and labels the raw status in plain words", async () => {
    const jobs = [
      { job_id: "job-old", filename: "old-waiting.json", status: "needs_review", error_code: null, run_id: null, created_at: "2026-10-01T08:00:00Z" },
      { job_id: "job-new", filename: "new-waiting.json", status: "needs_review", error_code: null, run_id: null, created_at: "2026-10-01T11:00:00Z" },
      { job_id: "job-done", filename: "checked.json", status: "submitted", error_code: null, run_id: "RUN-7", created_at: "2026-10-01T09:00:00Z" },
      { job_id: "job-bad", filename: "rejected.json", status: "rejected", error_code: "invalid_json", run_id: null, created_at: "2026-10-01T10:00:00Z" },
    ];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(jobs), { status: 200 })));
    render(<DocumentIntakePage />);
    const waiting = await screen.findByRole("heading", { name: "Waiting to be checked (2)" });
    const checked = screen.getByRole("heading", { name: "Checked (1)" });
    const rejected = screen.getByRole("heading", { name: "Rejected (1)" });
    expect(waiting.compareDocumentPosition(checked) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(checked.compareDocumentPosition(rejected) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const waitingSection = within(waiting.closest("section") as HTMLElement);
    expect(waitingSection.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent)).toEqual([
      "Waiting to be checked (2)", "new-waiting.json", "old-waiting.json",
    ]);
    expect(waitingSection.getAllByRole("button", { name: "Start check" })).toHaveLength(2);
    const rejectedSection = within(rejected.closest("section") as HTMLElement);
    expect(rejectedSection.getByText(/The file is not valid JSON/)).toBeInTheDocument();
    expect(rejectedSection.queryByRole("button", { name: "Start check" })).not.toBeInTheDocument();
    expect(screen.queryByText("needs_review")).not.toBeInTheDocument();
    expect(within(checked.closest("section") as HTMLElement).getByRole("link", { name: "Open findings" })).toHaveAttribute("href", "/workspace/my-queue?run=RUN-7");
  });

  it("checks only the package whose row was started and leaves the others waiting", async () => {
    const first = { job_id: "job-1", filename: "one.json", status: "needs_review", error_code: null, run_id: null, created_at: "2026-10-01T11:00:00Z" };
    const second = { job_id: "job-2", filename: "two.json", status: "needs_review", error_code: null, run_id: null, created_at: "2026-10-01T10:00:00Z" };
    const gate: { release?: () => void } = {};
    let started = false;
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/v1/intake-jobs") {
        const jobs = started ? [{ ...first, status: "submitted", run_id: "RUN-42" }, second] : [first, second];
        return Promise.resolve(new Response(JSON.stringify(jobs), { status: 200 }));
      }
      if (url === "/v1/intake-jobs/job-1/submit" && init?.method === "POST") {
        started = true;
        return new Promise<Response>((resolve) => { gate.release = () => resolve(new Response(JSON.stringify({ run: { run_id: "RUN-42" } }), { status: 200 })); });
      }
      return Promise.reject(new Error(`unexpected request ${init?.method ?? "GET"} ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<DocumentIntakePage />);
    const row = async (filename: string) => (await screen.findByRole("heading", { name: filename })).closest("article") as HTMLElement;
    fireEvent.click(within(await row("one.json")).getByRole("button", { name: "Start check" }));
    await waitFor(() => expect(within(screen.getByRole("heading", { name: "one.json" }).closest("article") as HTMLElement).getByRole("button", { name: "Start check" })).toBeDisabled());
    expect(within(screen.getByRole("heading", { name: "one.json" }).closest("article") as HTMLElement).getByText("Checking…")).toBeInTheDocument();
    expect(within(await row("two.json")).getByRole("button", { name: "Start check" })).toBeEnabled();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/submit")).map(([url]) => String(url))).toEqual(["/v1/intake-jobs/job-1/submit"]);
    gate.release?.();
    await waitFor(() => expect(screen.getByRole("heading", { name: "Checked (1)" })).toBeInTheDocument());
    const checkedSection = within(screen.getByRole("heading", { name: "Checked (1)" }).closest("section") as HTMLElement);
    expect(checkedSection.getByText("Checked run: RUN-42")).toBeInTheDocument();
    expect(checkedSection.getByRole("link", { name: "Open findings" })).toHaveAttribute("href", "/workspace/my-queue?run=RUN-42");
    expect(screen.getByRole("status")).toHaveTextContent("Claim checked and recorded as RUN-42.");
    expect(within(screen.getByRole("heading", { name: "Waiting to be checked (1)" }).closest("section") as HTMLElement).getByRole("button", { name: "Start check" })).toBeEnabled();
  });
});

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ClinicPortal } from "./clinic-portal";

const { getSession, signIn, replace } = vi.hoisted(() => ({ getSession: vi.fn(), signIn: vi.fn(), replace: vi.fn() }));
vi.mock("../lib/clinic-api", () => ({ getSession, signIn, signOut: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("./review-workspace-app", () => ({ ReviewWorkspaceApp: () => <div>Live claim cockpit</div> }));
vi.mock("./ops-console", () => ({ OpsConsole: ({ section }: { section: string }) => <div>{`ops-console:${section}`}</div> }));
vi.mock("./clinic-workflow-pages", () => ({
  ClinicReportPage: ({ page }: { page: string }) => <div>{`clinic-report:${page}`}</div>,
  ConfigurationPage: () => <div>configuration-page</div>,
  DocumentIntakePage: () => <div>intake-page</div>,
  WorkItemsPage: () => <div>work-items-page</div>,
}));

beforeEach(() => {
  getSession.mockReset();
  signIn.mockReset();
  replace.mockReset();
});

describe("clinic portal", () => {
  it.each([
    ["rcm_reviewer", ["My Queue", "Document Intake", "Requests", "Activity"]],
    ["rcm_lead", ["Team Queue", "Assignments", "Escalations", "Review Quality"]],
    ["clinic_admin", ["Overview", "All Claims", "Assignments", "Departments", "Team & Access", "Analytics", "Audit"]],
    ["technical_manager", ["Operations", "Metrics", "Traces", "Audit Integrity", "Intake Jobs", "Versions", "Configuration", "Platform Activity", "Roles"]],
  ])("shows the complete %s workspace", async (role, labels) => {
    getSession.mockResolvedValue({ user_id: "person-1", tenant_id: "clinic-a", role });
    render(<ClinicPortal page="unknown" />);
    for (const label of labels) expect(await screen.findByRole("link", { name: label })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Claim Workspace" })).not.toBeInTheDocument();
  });

  it("requires sign-in and opens the reviewer's real queue after authentication", async () => {
    getSession.mockResolvedValue(null);
    signIn.mockResolvedValue({ user_id: "reviewer-1", tenant_id: "clinic-a", role: "rcm_reviewer" });
    render(<ClinicPortal page="my-queue" />);

    expect(await screen.findByRole("heading", { name: /sign in/i })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/clinic id/i), { target: { value: "clinic-a" } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "reviewer@example.test" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "strong-password" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(screen.getByText("Live claim cockpit")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "My Queue" })).toHaveAttribute("href", "/workspace/my-queue");
    expect(screen.queryByRole("link", { name: "Operations" })).not.toBeInTheDocument();
  });

  it("collapses and reopens the workspace navigation", async () => {
    getSession.mockResolvedValue({ user_id: "person-1", tenant_id: "clinic-a", role: "clinic_admin" });
    render(<ClinicPortal page="overview" />);
    const toggle = await screen.findByRole("button", { name: "Collapse navigation" });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Expand navigation" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Expand navigation" }));
    expect(screen.getByRole("button", { name: "Collapse navigation" })).toBeInTheDocument();
  });

  it("routes a newly signed-in user away from a page outside their role", async () => {
    getSession.mockResolvedValue(null);
    signIn.mockResolvedValue({ user_id: "reviewer-1", tenant_id: "clinic-a", role: "rcm_reviewer" });
    render(<ClinicPortal page="assignments" />);
    fireEvent.change(await screen.findByLabelText(/clinic id/i), { target: { value: "clinic-a" } });
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: "reviewer@example.test" } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: "strong-password" } });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspace/my-queue"));
  });

  it("redirects an existing lead's old Claim Workspace bookmark to My Queue", async () => {
    getSession.mockResolvedValue({ user_id: "lead-1", tenant_id: "clinic-a", role: "rcm_lead" });
    render(<ClinicPortal page="claim-workspace" />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/workspace/my-queue"));
    expect(screen.queryByRole("link", { name: "Claim Workspace" })).not.toBeInTheDocument();
  });

  // Regression: the technical manager's Platform Activity page shared the "activity" page id with the
  // clinic Activity page, so both components mounted and the clinic page (which this role may not read)
  // took the whole page down. The operator page id is now distinct.
  it("gives the technical manager the operator console for Platform Activity, and never the clinic page", async () => {
    getSession.mockResolvedValue({ user_id: "tm-1", tenant_id: "clinic-a", role: "technical_manager" });
    render(<ClinicPortal page="platform-activity" />);
    expect(await screen.findByText("ops-console:activity")).toBeInTheDocument();
    expect(screen.queryByText("clinic-report:platform-activity")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Platform Activity" })).toHaveAttribute("href", "/workspace/platform-activity");
  });

  it("still gives clinic roles their own activity page", async () => {
    getSession.mockResolvedValue({ user_id: "lead-1", tenant_id: "clinic-a", role: "rcm_lead" });
    render(<ClinicPortal page="activity" />);
    expect(await screen.findByText("clinic-report:activity")).toBeInTheDocument();
    expect(screen.queryByText("ops-console:activity")).not.toBeInTheDocument();
  });

  it("renders the roles console for the technical manager without a clinic page", async () => {
    getSession.mockResolvedValue({ user_id: "tm-1", tenant_id: "clinic-a", role: "technical_manager" });
    render(<ClinicPortal page="roles" />);
    expect(await screen.findByText("ops-console:roles")).toBeInTheDocument();
    expect(screen.queryByText(/^clinic-report:/)).not.toBeInTheDocument();
  });
});

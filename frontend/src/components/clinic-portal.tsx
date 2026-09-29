"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Activity, BarChart3, ChevronLeft, ChevronRight, ClipboardList, FileClock, FileText, FolderInput, Gauge, LayoutDashboard, ListChecks, Menu, Settings2, ShieldCheck, ShieldEllipsis, Users, Workflow, X, type LucideIcon } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

import { getSession, signIn, signOut, type ClinicRole, type ClinicSession } from "../lib/clinic-api";
import { ReviewWorkspaceApp } from "./review-workspace-app";
import { AssignmentsPage } from "./assignments-page";
import { OperationsPage } from "./operations-page";
import { TeamAccessPage } from "./team-access-page";
import { DepartmentsPage } from "./departments-page";
import { ClinicReportPage, ConfigurationPage, DocumentIntakePage, WorkItemsPage } from "./clinic-workflow-pages";

type Destination = { label: string; page: string };

const ROLE_LABEL: Record<ClinicRole, string> = {
  rcm_reviewer: "RCM reviewer",
  rcm_lead: "RCM lead",
  clinic_admin: "Clinic admin",
  technical_manager: "Technical manager",
};

const NAV_ICONS: Record<string, LucideIcon> = {
  "my-queue": ListChecks, "team-queue": ListChecks, "all-claims": ClipboardList,
  "document-intake": FolderInput, "claim-workspace": FileText, requests: FileClock,
  activity: Activity, assignments: Workflow, escalations: ShieldEllipsis,
  "review-quality": BarChart3, overview: LayoutDashboard, departments: Workflow,
  "team-access": Users, analytics: BarChart3, audit: ShieldCheck,
  operations: Gauge, "intake-operations": FolderInput, versions: ListChecks,
  "redacted-logs": FileText, "audit-integrity": ShieldCheck, configuration: Settings2,
};

const NAVIGATION: Record<ClinicRole, Destination[]> = {
  rcm_reviewer: [
    { label: "My Queue", page: "my-queue" },
    { label: "Document Intake", page: "document-intake" },
    { label: "Requests", page: "requests" },
    { label: "Activity", page: "activity" },
  ],
  rcm_lead: [
    { label: "Team Queue", page: "team-queue" },
    { label: "Assignments", page: "assignments" },
    { label: "Escalations", page: "escalations" },
    { label: "Review Quality", page: "review-quality" },
    { label: "My Queue", page: "my-queue" },
    { label: "Document Intake", page: "document-intake" },
    { label: "Requests", page: "requests" },
    { label: "Activity", page: "activity" },
  ],
  clinic_admin: [
    { label: "Overview", page: "overview" },
    { label: "All Claims", page: "all-claims" },
    { label: "Assignments", page: "assignments" },
    { label: "Departments", page: "departments" },
    { label: "Team & Access", page: "team-access" },
    { label: "Analytics", page: "analytics" },
    { label: "Audit", page: "audit" },
  ],
  technical_manager: [
    { label: "Operations", page: "operations" },
    { label: "Intake Jobs", page: "intake-operations" },
    { label: "Model & Rule Versions", page: "versions" },
    { label: "Redacted Logs", page: "redacted-logs" },
    { label: "Audit Integrity", page: "audit-integrity" },
    { label: "Configuration", page: "configuration" },
  ],
};

export function ClinicPortal({ page }: { page: string }) {
  const router = useRouter();
  const [session, setSession] = useState<ClinicSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tenantId, setTenantId] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  function toggleNavigation() {
    setCollapsed((wasCollapsed) => !wasCollapsed);
  }

  useEffect(() => {
    void getSession().then(setSession).catch((cause) => {
      setError(cause instanceof Error ? cause.message : "The clinic session could not be loaded.");
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (session && page === "claim-workspace") {
      const destination = session.role === "rcm_reviewer" || session.role === "rcm_lead"
        ? "my-queue"
        : NAVIGATION[session.role][0].page;
      router.replace(`/workspace/${destination}`);
    }
  }, [page, router, session]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const signedIn = await signIn(tenantId, email, password);
      setSession(signedIn);
      if (page === "claim-workspace" && ["rcm_reviewer", "rcm_lead"].includes(signedIn.role)) {
        router.replace("/workspace/my-queue");
      } else if (page !== "home" && !NAVIGATION[signedIn.role].some((destination) => destination.page === page)) {
        router.replace(`/workspace/${NAVIGATION[signedIn.role][0].page}`);
      }
      setPassword("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign-in failed.");
    } finally {
      setLoading(false);
    }
  }

  async function leave() {
    setError(null);
    try {
      await signOut();
      setSession(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Sign-out failed.");
    }
  }

  if (loading && !session) return <main className="clinic-entry"><p>Checking clinic access…</p></main>;

  if (!session) return (
    <main className="clinic-entry">
      <section className="clinic-login" aria-labelledby="clinic-login-heading">
        <p className="eyebrow">ClaimGuard clinic workspace</p>
        <h1 id="clinic-login-heading">Sign in</h1>
        <p>Use the clinic ID and credentials provided by your clinic admin.</p>
        {error ? <p role="alert" className="clinic-error">{error}</p> : null}
        <form onSubmit={(event) => void submit(event)}>
          <label>Clinic ID<Input required value={tenantId} onChange={(event) => setTenantId(event.target.value)} /></label>
          <label>Email<Input required type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label>Password<Input required type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <Button className="primary-button" type="submit" disabled={loading}>Sign in</Button>
        </form>
      </section>
    </main>
  );

  const destinations = NAVIGATION[session.role];
  const activePage = page === "home" ? destinations[0].page : page === "claim-workspace" && ["rcm_reviewer", "rcm_lead"].includes(session.role) ? "my-queue" : page;
  const selected = destinations.find((destination) => destination.page === activePage);
  const cockpit = ["my-queue", "team-queue", "all-claims"].includes(activePage);
  return (
    <div className="clinic-shell" data-collapsed={collapsed}>
      <header className="clinic-mobile-header">
        <Button type="button" variant="outline" size="icon" className="icon-button" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={20} /></Button>
        <span><ShieldCheck size={20} /> ClaimGuard</span>
        <span className="clinic-mobile-role">{ROLE_LABEL[session.role]}</span>
      </header>
      {mobileOpen ? <button type="button" className="clinic-nav-backdrop" aria-label="Close navigation" onClick={() => setMobileOpen(false)} /> : null}
      <aside className="clinic-sidebar" data-open={mobileOpen}>
        <div className="clinic-sidebar-head">
          <Link className="clinic-brand" href={`/workspace/${destinations[0].page}`} title="ClaimGuard"><ShieldCheck size={21} /><span>ClaimGuard</span></Link>
          <Button type="button" variant="ghost" size="icon" className="clinic-collapse-button" aria-label={collapsed ? "Expand navigation" : "Collapse navigation"} onClick={toggleNavigation}>{collapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}</Button>
          <Button type="button" variant="ghost" size="icon" className="clinic-mobile-close" aria-label="Close navigation" onClick={() => setMobileOpen(false)}><X size={18} /></Button>
        </div>
        <p className="clinic-identity">{session.tenant_id}</p>
        <nav aria-label="Workspace">
          {destinations.map((destination) => {
            const Icon = NAV_ICONS[destination.page];
            return <Link key={destination.page} href={`/workspace/${destination.page}`} title={destination.label} aria-current={activePage === destination.page ? "page" : undefined} onClick={() => setMobileOpen(false)}><Icon className="clinic-nav-icon" size={18} aria-hidden="true" /><span className="clinic-nav-label">{destination.label}</span></Link>;
          })}
        </nav>
        <div className="clinic-account">
          <p title={session.user_id}>{ROLE_LABEL[session.role]}</p>
          <Button type="button" variant="outline" onClick={() => void leave()}>Sign out</Button>
        </div>
      </aside>
      <div className="clinic-main" role={cockpit ? undefined : "main"}>
        {error ? <p role="alert" className="clinic-error">{error}</p> : null}
        {!selected ? <section><h1>Access denied</h1><p>This page is not available to your role.</p></section> : null}
        {selected && cockpit ? (
          <ReviewWorkspaceApp reviewer={session.user_id} scope={["team-queue", "all-claims"].includes(activePage) ? "team" : "mine"} includeAll={activePage === "all-claims"} />
        ) : null}
        {selected && activePage === "assignments" ? <AssignmentsPage claimPage={session.role === "clinic_admin" ? "all-claims" : "team-queue"} /> : null}
        {selected && activePage === "operations" ? <OperationsPage /> : null}
        {selected && activePage === "team-access" ? <TeamAccessPage /> : null}
        {selected && activePage === "departments" ? <DepartmentsPage /> : null}
        {selected && activePage === "document-intake" ? <DocumentIntakePage /> : null}
        {selected && activePage === "requests" ? <WorkItemsPage kind="requests" /> : null}
        {selected && activePage === "escalations" ? <WorkItemsPage kind="escalations" /> : null}
        {selected && activePage === "configuration" ? <ConfigurationPage /> : null}
        {selected && ["activity", "review-quality", "overview", "analytics", "audit", "intake-operations", "versions", "redacted-logs", "audit-integrity"].includes(activePage) ? <ClinicReportPage page={activePage} /> : null}
      </div>
    </div>
  );
}

"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import type { ClinicRole } from "../lib/clinic-api";

type Member = { user_id: string; email: string; display_name: string | null; role: ClinicRole; active: boolean };

async function memberJson(response: Response): Promise<Member> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail ?? `Account request failed (${response.status}).`);
  }
  return await response.json() as Member;
}

export function TeamAccessPage() {
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<ClinicRole>("rcm_reviewer");
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/v1/team?include_inactive=true", { cache: "no-store" });
      if (!response.ok) throw new Error(`Team could not be loaded (${response.status}).`);
      setMembers(await response.json() as Member[]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Team could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const member = await memberJson(await fetch("/v1/team", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, display_name: displayName || null, password, role }),
      }));
      setMembers((current) => [...current, member]);
      setEmail(""); setDisplayName(""); setPassword("");
      setNotice(`Account created for ${member.email}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Account could not be created.");
    } finally {
      setSaving(false);
    }
  }

  async function setActive(member: Member) {
    setError(null);
    setNotice(null);
    try {
      const updated = await memberJson(await fetch(`/v1/team/${encodeURIComponent(member.user_id)}/status`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ active: !member.active }),
      }));
      setMembers((current) => current.map((item) => item.user_id === updated.user_id ? updated : item));
      setNotice(`${updated.email} is now ${updated.active ? "active" : "inactive"}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Membership could not be updated.");
    }
  }

  return <section className="clinic-page" aria-busy={busy || saving}>
    <header className="clinic-page-heading"><div><p className="eyebrow">Clinic administration</p><h1>Team &amp; Access</h1></div><button type="button" className="secondary-button" onClick={() => void load()} disabled={busy}>Refresh</button></header>
    <p>Create accounts and revoke access to this clinic. Passwords are never displayed after creation.</p>
    {error ? <p className="clinic-error" role="alert">{error}</p> : null}
    {notice ? <p className="clinic-success" role="status">{notice}</p> : null}
    <form className="clinic-form" onSubmit={(event) => void create(event)}>
      <h2>New team member</h2>
      <label>Email<input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      <label>Display name<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
      <label>Role<select value={role} onChange={(event) => setRole(event.target.value as ClinicRole)}>
        <option value="rcm_reviewer">RCM reviewer</option><option value="rcm_lead">RCM lead</option><option value="clinic_admin">Clinic admin</option><option value="technical_manager">Technical manager</option>
      </select></label>
      <label>Password<input type="password" minLength={12} required value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <button className="primary-button" type="submit" disabled={saving}>Create account</button>
    </form>
    {busy ? <p>Loading team…</p> : null}
    {!busy && members.length === 0 ? <p>No team members have been added yet.</p> : null}
    {!busy && members.length > 0 ? <div className="clinic-table-wrap"><table className="clinic-table"><thead><tr><th>Member</th><th>Role</th><th>Status</th><th>Access</th></tr></thead><tbody>
      {members.map((member) => <tr key={member.user_id}><td><strong>{member.email}</strong><br />{member.display_name}</td><td>{member.role.replaceAll("_", " ")}</td><td>{member.active ? "Active" : "Inactive"}</td><td><button type="button" className="secondary-button" onClick={() => void setActive(member)}>{member.active ? `Deactivate ${member.email}` : `Activate ${member.email}`}</button></td></tr>)}
    </tbody></table></div> : null}
  </section>;
}

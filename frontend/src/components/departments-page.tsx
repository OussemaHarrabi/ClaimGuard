"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

type Department = { department_id: string; name: string; active: boolean };

async function departmentJson(response: Response): Promise<Department> {
  if (!response.ok) {
    const payload = await response.json().catch(() => ({})) as { detail?: string };
    throw new Error(payload.detail ?? `Department request failed (${response.status}).`);
  }
  return await response.json() as Department;
}

export function DepartmentsPage() {
  const [departments, setDepartments] = useState<Department[]>([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/v1/departments", { cache: "no-store" });
      if (!response.ok) throw new Error(`Departments could not be loaded (${response.status}).`);
      setDepartments(await response.json() as Department[]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Departments could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const created = await departmentJson(await fetch("/v1/departments", {
        method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name }),
      }));
      setDepartments((current) => [...current, created]);
      setName("");
      setNotice(`${created.name} was added.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Department could not be added.");
    } finally {
      setSaving(false);
    }
  }

  async function setActive(department: Department) {
    setError(null);
    setNotice(null);
    try {
      const updated = await departmentJson(await fetch(`/v1/departments/${encodeURIComponent(department.department_id)}/update`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: department.name, active: !department.active }),
      }));
      setDepartments((current) => current.map((item) => item.department_id === updated.department_id ? updated : item));
      setNotice(`${updated.name} is now ${updated.active ? "active" : "inactive"}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Department could not be updated.");
    }
  }

  return <section className="clinic-page" aria-busy={busy || saving}>
    <header className="clinic-page-heading"><div><p className="eyebrow">Clinic administration</p><h1>Departments</h1></div><button className="secondary-button" type="button" onClick={() => void load()} disabled={busy}>Refresh</button></header>
    <p>Organize clinic teams and keep inactive departments visible in the record.</p>
    {error ? <p className="clinic-error" role="alert">{error}</p> : null}
    {notice ? <p className="clinic-success" role="status">{notice}</p> : null}
    <form className="clinic-form" onSubmit={(event) => void add(event)}><label>Department name<input required value={name} onChange={(event) => setName(event.target.value)} /></label><button className="primary-button" type="submit" disabled={saving}>Add department</button></form>
    {busy ? <p>Loading departments…</p> : null}
    {!busy && departments.length === 0 ? <p>No departments have been added yet.</p> : null}
    {!busy && departments.length > 0 ? <div className="clinic-table-wrap"><table className="clinic-table"><thead><tr><th>Department</th><th>Status</th><th>Action</th></tr></thead><tbody>
      {departments.map((department) => <tr key={department.department_id}><td>{department.name}</td><td>{department.active ? "Active" : "Inactive"}</td><td><button type="button" className="secondary-button" onClick={() => void setActive(department)}>{department.active ? `Deactivate ${department.name}` : `Activate ${department.name}`}</button></td></tr>)}
    </tbody></table></div> : null}
  </section>;
}

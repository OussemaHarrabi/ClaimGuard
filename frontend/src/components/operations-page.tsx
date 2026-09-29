"use client";

import { useCallback, useEffect, useState } from "react";

type Operations = {
  status: string;
  database: string;
  schema_revision: string | null;
  rules_ready: boolean;
  engine_rule_version: string;
};

export function OperationsPage() {
  const [operations, setOperations] = useState<Operations | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/v1/operations", { cache: "no-store" });
      if (!response.ok) throw new Error(`Operations could not be loaded (${response.status}).`);
      setOperations(await response.json() as Operations);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Operations could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return <section className="clinic-page" aria-busy={busy}>
    <header className="clinic-page-heading"><div><p className="eyebrow">Service status</p><h1>Operations</h1></div><button type="button" className="secondary-button" disabled={busy} onClick={() => void load()}>Refresh</button></header>
    <p>Service readiness only. Claim content is not available in this workspace.</p>
    {error ? <p role="alert" className="clinic-error">{error}</p> : null}
    {busy ? <p>Checking services…</p> : null}
    {operations ? <dl className="clinic-status-list">
      <div><dt>Service</dt><dd>{operations.status}</dd></div>
      <div><dt>Database</dt><dd>{operations.database}</dd></div>
      <div><dt>Schema revision</dt><dd>{operations.schema_revision ?? "Unavailable"}</dd></div>
      <div><dt>Rule catalogue</dt><dd>{operations.rules_ready ? "ready" : "unavailable"}</dd></div>
      <div><dt>Engine rule version</dt><dd>{operations.engine_rule_version}</dd></div>
    </dl> : null}
  </section>;
}

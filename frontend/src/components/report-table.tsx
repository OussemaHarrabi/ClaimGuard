"use client";

import { useState } from "react";
import { ArrowDownUp, ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

type Row = Record<string, unknown>;
const LABELS: Record<string, string> = { at: "Recorded at", kind: "Activity", initiated_by: "Started by", run_id: "Run reference", claim_id: "Claim", actor: "Team member", created_at: "Created", model_version: "Model version", rule_version: "Rule version", prompt_version: "Prompt version", audit_hash: "Audit hash" };
function readable(value: unknown) {
  if (value === null || value === undefined) return "Not recorded";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function ReportTable({ rows, empty = "No records yet." }: { rows: Row[]; empty?: string }) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ key: string; descending: boolean } | null>(null);
  const [page, setPage] = useState(0);
  const columns = Object.keys(rows[0] ?? {});
  const filtered = rows.filter((row) => Object.values(row).some((value) => readable(value).toLowerCase().includes(query.trim().toLowerCase())));
  if (sort) filtered.sort((a, b) => readable(a[sort.key]).localeCompare(readable(b[sort.key]), "en", { numeric: true }) * (sort.descending ? -1 : 1));
  const pages = Math.max(1, Math.ceil(filtered.length / 12));
  const currentPage = Math.min(page, pages - 1);
  if (!rows.length) return <p className="clinic-empty">{empty}</p>;
  return <div><div className="report-toolbar"><Input aria-label="Search records" type="search" placeholder="Search activity, people, or references…" value={query} onChange={(event) => { setQuery(event.target.value); setPage(0); }} /><span>{filtered.length} records</span></div>
    <div className="clinic-table-wrap"><table className="clinic-table"><thead><tr>{columns.map((key) => <th key={key} aria-sort={sort?.key === key ? sort.descending ? "descending" : "ascending" : "none"}><button type="button" className="report-sort" onClick={() => { setSort({ key, descending: sort?.key === key && !sort.descending }); setPage(0); }}>{LABELS[key] ?? key.replaceAll("_", " ")}<ArrowDownUp size={12} /></button></th>)}</tr></thead><tbody>{filtered.slice(currentPage * 12, currentPage * 12 + 12).map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{row[key] && typeof row[key] === "object" ? <details className="report-detail"><summary>View details</summary><pre>{JSON.stringify(row[key], null, 2)}</pre></details> : <span title={String(row[key] ?? "")}>{readable(row[key])}</span>}</td>)}</tr>)}{!filtered.length ? <tr><td colSpan={columns.length}>No records match your search.</td></tr> : null}</tbody></table></div>
    <div className="report-pagination"><Button variant="outline" size="sm" aria-label="Previous page" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={15} /></Button><span>Page {currentPage + 1} of {pages}</span><Button variant="outline" size="sm" aria-label="Next page" disabled={currentPage === pages - 1} onClick={() => setPage(currentPage + 1)}><ChevronRight size={15} /></Button></div>
  </div>;
}

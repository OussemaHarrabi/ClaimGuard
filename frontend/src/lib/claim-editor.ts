/** Edit only a scalar field already present in the stored claim envelope. */
function segments(pointer: string): string[] {
  if (!pointer.startsWith("/") || pointer === "/") throw new Error("This evidence path cannot be edited.");
  const parts = pointer.slice(1).split("/").map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"));
  if (parts.some((part) => !part || ["__proto__", "prototype", "constructor"].includes(part))) {
    throw new Error("This evidence path cannot be edited.");
  }
  return parts;
}

export function readPointer(claim: unknown, pointer: string): unknown {
  let current = claim;
  for (const part of segments(pointer)) {
    if (!current || typeof current !== "object" || !Object.hasOwn(current, part)) return undefined;
    current = (current as Record<string, unknown>)[part];
  }
  return current;
}

/** Prioritize editable evidence from checks that have not passed. */
export function editableEvidencePaths(
  findings: readonly { status: string; evidence: readonly { path: string }[] }[],
  claim: unknown,
): string[] {
  const paths = new Set<string>();
  for (const finding of findings) {
    if (finding.status === "PASS") continue;
    for (const evidence of finding.evidence) {
      try {
        const value = readPointer(claim, evidence.path);
        if (value === null || typeof value === "string" || typeof value === "number") {
          paths.add(evidence.path);
        }
      } catch {
        // Some evidence is computed rather than a claim field.
      }
    }
  }
  return [...paths];
}

const FIELD_NAMES: Readonly<Record<string, string>> = {
  claim_id: "claim ID", invoice_number: "invoice number", patient_id: "patient ID",
  member_id: "member ID", provider_id: "provider ID", payer_id: "payer ID",
  policy_id: "policy ID", diagnosis_code: "diagnosis code",
  submission_date: "submission date", total_amount: "claim total",
  coverage_id: "coverage ID", beneficiary_patient_id: "covered patient ID",
  start_date: "start date", end_date: "end date", status: "status",
  line_id: "line ID", service_code: "service code", service_date: "service date",
  unit_price: "unit price", net_amount: "line amount", quantity: "quantity",
  authorization_id: "authorization ID", valid_from: "valid from", valid_to: "valid until",
  max_quantity: "maximum quantity", attachment_id: "document ID",
  document_status: "document status", currency: "currency", notes: "notes",
};

/** A reviewer-facing label; the original pointer remains in the advanced JSON. */
export function fieldLabel(pointer: string): string {
  const parts = segments(pointer);
  const field = parts.at(-1)!;
  const name = FIELD_NAMES[field] ?? field.replaceAll("_", " ");
  const container = parts[0];
  if (container === "coverage") return `Coverage · ${name}`;
  if (["lines", "authorizations", "attachments"].includes(container) && /^\d+$/.test(parts[1] ?? "")) {
    const entity = container === "lines" ? "Line" : container === "authorizations" ? "Authorization" : "Document";
    return `${entity} ${Number(parts[1]) + 1} · ${name}`;
  }
  return name.charAt(0).toUpperCase() + name.slice(1);
}

type CorrectableFinding = {
  ruleId: string;
  status: string;
  explanation: string;
  correctionRecommendation: string;
  evidence: readonly { path: string }[];
};

export function buildCorrectionGroups(findings: readonly CorrectableFinding[], claim: unknown) {
  return findings
    .filter((finding) => ["FAIL", "UNABLE_TO_ASSESS"].includes(finding.status))
    .map((finding) => ({
      ruleId: finding.ruleId,
      explanation: finding.explanation,
      recommendation: finding.correctionRecommendation,
      fields: editableEvidencePaths([finding], claim).map((path) => ({ path, label: fieldLabel(path) })),
    }));
}

export function plainIssue(explanation: string): string {
  const detected = explanation.match(/Detected:\s*(.*?)\.\s*Evidence\s*\(/s)?.[1];
  if (detected) return `${detected.charAt(0).toUpperCase()}${detected.slice(1)}.`;
  return explanation.replace(/^\[deterministic\]\s*/, "");
}

export function plainRecommendation(recommendation: string): string {
  return recommendation.replace(/^\[deterministic\]\s*/, "");
}

export function updatePointer(text: string, pointer: string, input: string): string {
  const claim = JSON.parse(text) as Record<string, unknown>;
  const path = segments(pointer);
  let parent: unknown = claim;
  for (const part of path.slice(0, -1)) {
    if (!parent || typeof parent !== "object" || !Object.hasOwn(parent, part)) throw new Error("Evidence field is missing from this claim.");
    parent = (parent as Record<string, unknown>)[part];
  }
  const leaf = path.at(-1)!;
  if (!parent || typeof parent !== "object" || !Object.hasOwn(parent, leaf)) throw new Error("Evidence field is missing from this claim.");
  const record = parent as Record<string, unknown>;
  const previous = record[leaf];
  if (previous !== null && typeof previous !== "string" && typeof previous !== "number") throw new Error("This evidence field needs advanced editing.");
  const numeric = typeof previous === "number" || (previous === null && /(?:amount|price|quantity|total)$/i.test(leaf));
  if (numeric) {
    const parsed = input.trim() === "" ? null : Number(input);
    if (parsed !== null && !Number.isFinite(parsed)) throw new Error("Enter a valid number for this field.");
    record[leaf] = parsed;
  } else {
    record[leaf] = input;
  }
  return JSON.stringify(claim, null, 2);
}

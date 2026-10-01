import { describe, expect, it } from "vitest";

import { buildCorrectionGroups, editableEvidencePaths, fieldLabel, plainIssue, plainRecommendation, readPointer, updatePointer } from "./claim-editor";

const claim = { claim_id: "CG-1", coverage: { end_date: "2026-04-29" }, lines: [{ net_amount: 240, unit_price: null }] };

describe("evidence-backed claim editor", () => {
  it("reads and edits existing nested fields without changing the original claim", () => {
    const original = JSON.stringify(claim);
    const changed = updatePointer(original, "/coverage/end_date", "2026-04-30");
    expect(readPointer(JSON.parse(changed), "/coverage/end_date")).toBe("2026-04-30");
    expect(JSON.stringify(claim)).toBe(original);
  });

  it("retains numeric field types and permits missing numeric evidence to be filled", () => {
    const first = updatePointer(JSON.stringify(claim), "/lines/0/net_amount", "250.5");
    const second = updatePointer(first, "/lines/0/unit_price", "125.25");
    expect(readPointer(JSON.parse(second), "/lines/0/net_amount")).toBe(250.5);
    expect(readPointer(JSON.parse(second), "/lines/0/unit_price")).toBe(125.25);
  });

  it("refuses new or unsafe paths and invalid numeric values", () => {
    expect(() => updatePointer(JSON.stringify(claim), "/coverage/unknown", "x")).toThrow();
    expect(() => updatePointer(JSON.stringify(claim), "/__proto__/polluted", "x")).toThrow();
    expect(() => updatePointer(JSON.stringify(claim), "/lines/0/net_amount", "not-a-number")).toThrow();
  });

  it("guides correction toward scalar evidence from non-passing findings only", () => {
    expect(editableEvidencePaths([
      { status: "PASS", evidence: [{ path: "/claim_id" }] },
      { status: "FAIL", evidence: [{ path: "/coverage/end_date" }, { path: "/lines" }] },
      { status: "UNABLE_TO_ASSESS", evidence: [{ path: "/lines/0/net_amount" }, { path: "/coverage/end_date" }] },
    ], claim)).toEqual(["/coverage/end_date", "/lines/0/net_amount"]);
  });

  it("uses clinical-business labels rather than JSON array paths", () => {
    expect(fieldLabel("/lines/0/unit_price")).toBe("Line 1 · unit price");
    expect(fieldLabel("/coverage/end_date")).toBe("Coverage · end date");
    expect(fieldLabel("/authorizations/1/valid_to")).toBe("Authorization 2 · valid until");
  });

  it("groups editable evidence with its own rule explanation and recommendation", () => {
    expect(buildCorrectionGroups([
      { ruleId: "R003", status: "FAIL", explanation: "Coverage ended before service.", correctionRecommendation: "Verify the coverage period with the insurer.", evidence: [{ path: "/coverage/end_date" }] },
      { ruleId: "R007", status: "FAIL", explanation: "Line arithmetic differs.", correctionRecommendation: "Recalculate from the invoice.", evidence: [{ path: "/lines/0/unit_price" }] },
      { ruleId: "R012", status: "PASS", explanation: "Total matches.", correctionRecommendation: "No change.", evidence: [{ path: "/claim_id" }] },
    ], claim)).toEqual([
      { ruleId: "R003", explanation: "Coverage ended before service.", recommendation: "Verify the coverage period with the insurer.", fields: [{ path: "/coverage/end_date", label: "Coverage · end date" }] },
      { ruleId: "R007", explanation: "Line arithmetic differs.", recommendation: "Recalculate from the invoice.", fields: [{ path: "/lines/0/unit_price", label: "Line 1 · unit price" }] },
    ]);
  });

  it("removes engine scaffolding from reviewer guidance without inventing a fix", () => {
    expect(plainIssue('Rule R003 reports FAIL. Detected: service outside coverage period. Evidence (5 pointers): /coverage/end_date.')).toBe("Service outside coverage period.");
    expect(plainRecommendation("[deterministic] Verify eligibility with the insurer.")).toBe("Verify eligibility with the insurer.");
  });
});

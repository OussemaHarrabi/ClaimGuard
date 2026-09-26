import { describe, expect, it } from "vitest";

import { demoWorkspace } from "./demo-workspace";

describe("demoWorkspace", () => {
  it("shows the deterministic provider selected by the measured benchmark", () => {
    expect(demoWorkspace.selected?.run.modelVersion).toBe("deterministic-engine/1.0.0");
    expect(demoWorkspace.selected?.run.promptVersion).toBe("none");
    expect(demoWorkspace.selected?.findings.every((finding) => finding.provenance.source === "deterministic")).toBe(true);
    expect(demoWorkspace.selected?.findings.every((finding) => finding.provenance.provider === "template")).toBe(true);
  });
});

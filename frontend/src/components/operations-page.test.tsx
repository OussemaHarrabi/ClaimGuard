import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { OperationsPage } from "./operations-page";

afterEach(() => vi.unstubAllGlobals());

it("shows live claim-blind service readiness", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    status: "ok", database: "ready", schema_revision: "0008", rules_ready: true,
    engine_rule_version: "1.0.0",
  }), { status: 200 })));
  render(<OperationsPage />);
  expect(await screen.findByText("0008")).toBeInTheDocument();
  expect(screen.getAllByText("ready")).toHaveLength(2);
  expect(screen.queryByText(/claim id/i)).not.toBeInTheDocument();
});

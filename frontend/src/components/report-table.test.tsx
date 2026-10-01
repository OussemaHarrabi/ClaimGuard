import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ReportTable } from "./report-table";

describe("report table", () => {
  it("preserves identifiers exactly for copying and searching", () => {
    render(<ReportTable rows={[{ claim_id: "CG_TEST_001" }]} />);
    expect(screen.getByText("CG_TEST_001")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "CG_TEST_001" } });
    expect(screen.getByText("CG_TEST_001")).toBeInTheDocument();
  });
  it("paginates, searches all records, and resets pagination on search", () => {
    render(<ReportTable rows={Array.from({ length: 15 }, (_, index) => ({ claim_id: `CLAIM-${index}`, kind: "claim_checked" }))} />);
    expect(screen.queryByText("CLAIM-14")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(screen.getByText("CLAIM-14")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "CLAIM-0" } });
    expect(screen.getByText("CLAIM-0")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });
});

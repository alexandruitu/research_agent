import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RUN_ID, runOut, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { RunComparePage } from "./RunComparePage";

afterEach(() => vi.unstubAllGlobals());

const B = "99999999-9999-4999-8999-999999999999";
const paper = (title: string) => ({ paper_id: "33333333-3333-4333-8333-33333333333" + title.length, source_id: `MED:${title.length}`, title, year: 2024 });

describe("compare runs", () => {
  it("marks configuration differences in words and lists papers that came out differently", async () => {
    mockApi({
      "GET /api/v1/auth/me": { body: session("viewer") },
      "GET /api/v1/runs": { body: [runOut({ kind: "research" }), runOut({ id: B, kind: "research", name: "Second" })] },
      "GET /api/v1/runs/compare": { body: {
        runs: [runOut({ kind: "research" }), runOut({ id: B, kind: "research", name: "Second" })],
        config: [{ label: "Mode", a: "live", b: "live", differs: false }, { label: "Papers to screen", a: "5", b: "10", differs: true }],
        kept_only_a: [paper("Kept by A")], kept_only_b: [], only_in_a: [], only_in_b: [paper("New in B paper")],
        score_changes: [{ ...paper("Scored"), a: 60, b: 72.5, delta: 12.5 }],
      } },
    });
    renderWithProviders(<RunComparePage />, { route: `/runs/compare?ids=${RUN_ID},${B}` });
    expect(await screen.findByText("1 difference")).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /Papers to screen/ });
    expect(within(row).getByText("differs")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Kept in A, dropped in B" })).toHaveTextContent("Kept by A");
    expect(screen.getByRole("region", { name: "Only in B" })).toHaveTextContent("New in B paper");
    expect(screen.getByText(/higher in B/)).toBeInTheDocument();
  });

  it("asks for two runs when fewer are given", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("viewer") }, "GET /api/v1/runs": { body: [] } });
    renderWithProviders(<RunComparePage />, { route: "/runs/compare" });
    expect(await screen.findByText(/Choose two runs/)).toBeInTheDocument();
  });
});

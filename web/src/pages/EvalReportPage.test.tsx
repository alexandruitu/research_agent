import { screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { EVAL_ID, evalDetail, evalMetrics, session } from "../test/fixtures";
import { mockApi, type MockHandler } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { EvalReportPage } from "./EvalReportPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(detail = evalDetail(), role: "viewer" | "member" | "admin" = "viewer", extra: Record<string, MockHandler> = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/evals/:id": { body: detail },
    ...extra,
  });
  renderWithProviders(<Routes><Route path="/evals/:evalId" element={<EvalReportPage />} /></Routes>, { route: `/evals/${detail.id}` });
  return api;
}

describe("Screening report", () => {
  it("opens the report and shows the summary cards with the exact numbers", async () => {
    setup();
    expect(await screen.findByRole("heading", { level: 2, name: /mlffrct-2024/ })).toBeInTheDocument();
    const cards = screen.getByRole("region", { name: "Summary" });
    expect(within(cards).getByText("15/16 (95% CI 0.72–0.99)", { exact: false })).toBeInTheDocument();
    expect(within(cards).getByText("include ≥ 0.1, exclude ≥ 0.7")).toBeInTheDocument();
    expect(within(cards).getByText("0.945")).toBeInTheDocument();
    expect(within(cards).getByText("same model family")).toBeInTheDocument();
  });

  it("names the kind in words and links back to all evaluations", async () => {
    setup();
    expect(await screen.findByRole("heading", { level: 1, name: /Screening/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "← All evaluations" })).toHaveAttribute("href", "/evals");
  });

  it("shows recall for the three strategies with intervals", async () => {
    setup();
    const rows = await screen.findByRole("table", { name: "Recall by strategy" });
    expect(within(rows).getByRole("row", { name: /cascade/ })).toHaveTextContent("15/16");
    expect(within(rows).getByRole("row", { name: /jev_only/ })).toHaveTextContent("14/16");
    expect(within(rows).getByRole("row", { name: /llm_only/ })).toHaveTextContent("0 calls saved");
  });

  it("draws the threshold grid: default outlined, recommended starred, risky pairs marked in words", async () => {
    setup();
    const grid = await screen.findByRole("table", { name: "Threshold grid" });
    const cell = (include: string, exclude: string) => within(grid).getByRole("cell", { name: new RegExp(`^include ${include}, exclude ${exclude}:`) });
    expect(cell("0.6", "0.9")).toHaveClass("is-default");
    expect(cell("0.6", "0.9")).toHaveTextContent("69");
    expect(cell("0.1", "0.7")).toHaveTextContent("★");
    expect(cell("0.1", "0.7")).toHaveTextContent("74");
    expect(cell("0.1", "0.5")).toHaveClass("is-risky");
    expect(cell("0.1", "0.5")).toHaveTextContent("loses 1 on the main set");
    expect(cell("0.6", "0.99")).toHaveClass("is-risky");
    expect(cell("0.6", "0.99")).toHaveTextContent("loses 1 on the holdout");
  });

  it("empty combinations are cells that say they are not allowed, not blanks", async () => {
    setup();
    const grid = await screen.findByRole("table", { name: "Threshold grid" });
    expect(within(grid).getAllByText("–").length).toBeGreaterThan(0);
  });

  it("explains the rejected pick and lists the caveats", async () => {
    setup();
    const banner = await screen.findByText(/Rejected on the holdout/);
    expect(banner).toHaveTextContent("include ≥ 0.1, exclude ≥ 0.5");
    expect(banner).toHaveTextContent("A holdout paper the pair would lose");
    expect(screen.getByRole("list", { name: "Caveats" })).toHaveTextContent("Rejected.");
  });

  it("does not double the full stop when a lost title already ends with one", async () => {
    const metrics = evalMetrics();
    setup(evalDetail({ ...metrics, rejected_on_holdout: { ...metrics.rejected_on_holdout, lost: [{ id: "MED:9", title: "Random Forest Analysis in Machine Learning." }] } }));
    const banner = await screen.findByText(/Rejected on the holdout/);
    expect(banner.textContent).toMatch(/Machine Learning\.$/);
  });

  it("says when the grid has no holdout to check against, and when nothing is recommended", async () => {
    setup(evalDetail({ ...evalMetrics(), holdout_sweep: null, holdout: null, rejected_on_holdout: null, recommended: null }));
    expect(await screen.findByText(/No holdout run: risky pairs can only be judged on the main set/)).toBeInTheDocument();
    expect(screen.getByText("No admissible pair")).toBeInTheDocument();
  });

  it("shows the request id when the report cannot be loaded", async () => {
    mockApi({
      "GET /api/v1/auth/me": { body: session("viewer") },
      "GET /api/v1/evals/:id": { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "req-9" } },
    });
    renderWithProviders(<Routes><Route path="/evals/:evalId" element={<EvalReportPage />} /></Routes>, { route: `/evals/${EVAL_ID}` });
    expect(await screen.findByRole("alert")).toHaveTextContent("req-9");
  });
});

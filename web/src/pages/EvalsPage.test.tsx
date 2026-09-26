import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { EVAL_ID, evalDetail, evalMetrics, evalSummary, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { EvalsPage } from "./EvalsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(detail = evalDetail(), summaries = [evalSummary()]) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session("viewer") },
    "GET /api/v1/evals": { body: summaries },
    "GET /api/v1/evals/:id": { body: detail },
  });
  renderWithProviders(<Routes><Route path="/evals" element={<EvalsPage />} /><Route path="/evals/:evalId" element={<EvalsPage />} /></Routes>, { route: "/evals" });
  return api;
}

describe("EvalsPage", () => {
  it("opens the newest eval set and shows the summary cards with the exact numbers", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: /mlffrct-2024/ })).toBeInTheDocument();
    const cards = screen.getByRole("region", { name: "Summary" });
    expect(within(cards).getByText("15/16 (95% CI 0.72–0.99)", { exact: false })).toBeInTheDocument();
    expect(within(cards).getByText("include ≥ 0.1, exclude ≥ 0.7")).toBeInTheDocument();
    expect(within(cards).getByText("0.945")).toBeInTheDocument();
    expect(within(cards).getByText("same model family")).toBeInTheDocument();
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

  it("says when the grid has no holdout to check against, and when nothing is recommended", async () => {
    setup(evalDetail({ ...evalMetrics(), holdout_sweep: null, holdout: null, rejected_on_holdout: null, recommended: null }));
    expect(await screen.findByText(/No holdout run: risky pairs can only be judged on the main set/)).toBeInTheDocument();
    expect(screen.getByText("No admissible pair")).toBeInTheDocument();
  });

  it("switches between eval sets", async () => {
    const second = evalSummary({ id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", gold_set: { id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", name: "aiffr-slr-2023", citation: "Other 2023" } });
    const { calls } = setup(evalDetail(), [evalSummary(), second]);
    await screen.findByRole("heading", { name: /mlffrct-2024/ });
    await userEvent.selectOptions(screen.getByLabelText("Eval set"), second.id);
    expect(calls.some((c) => c.path === `/api/v1/evals/${second.id}`)).toBe(true);
    expect(calls.some((c) => c.path === `/api/v1/evals/${EVAL_ID}`)).toBe(true);
  });

  it("says so when there are no eval reports", async () => {
    setup(evalDetail(), []);
    expect(await screen.findByText(/No eval reports yet/)).toBeInTheDocument();
  });

  it("shows the request id when the report cannot be loaded", async () => {
    mockApi({
      "GET /api/v1/auth/me": { body: session("viewer") },
      "GET /api/v1/evals": { body: [evalSummary()] },
      "GET /api/v1/evals/:id": { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "req-9" } },
    });
    renderWithProviders(<Routes><Route path="/evals" element={<EvalsPage />} /></Routes>, { route: "/evals" });
    expect(await screen.findByRole("alert")).toHaveTextContent("req-9");
  });
});

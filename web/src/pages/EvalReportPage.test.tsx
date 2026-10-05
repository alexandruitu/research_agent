import { screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import userEvent from "@testing-library/user-event";

import { EVAL_ID, PANEL_ID, SAMPLE_ID, evalDetail, evalMetrics, humanDetail, panelDetail, panelMetrics, ratingSample, session } from "../test/fixtures";
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

describe("Panel report", () => {
  const panel = (role: "viewer" | "member" | "admin" = "viewer", detail = panelDetail()) =>
    setup(detail, role, { "GET /api/v1/rating-samples/:id": { body: ratingSample() }, "POST /api/v1/evals/:id/rating-samples": { status: 201, body: ratingSample() } });

  it("shows Fleiss kappa with raw agreement and prevalence together, in words", async () => {
    panel();
    const summary = await screen.findByRole("region", { name: "Agreement at a glance" });
    expect(summary).toHaveTextContent("Fleiss kappa 0.42");
    expect(summary).toHaveTextContent("moderate");
    expect(summary).toHaveTextContent("73% raw agreement");
    expect(summary).toHaveTextContent("80% prevalence");
    expect(summary).toHaveTextContent("Editor agrees with the majority on 90% (9 of 10)");
    expect(screen.getByText(/kappa corrects for chance/i)).toBeInTheDocument();
  });

  it("ranks items worst-first with the text and a reword chip", async () => {
    panel();
    const table = await screen.findByRole("table", { name: "Agreement per checklist item" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows[0]).toHaveTextContent("Was the test set split by patient?");
    expect(rows[0]).toHaveTextContent("candidate to reword");
    expect(rows[0]).toHaveTextContent("80% not answered");
    expect(rows[1]).not.toHaveTextContent("candidate to reword");
  });

  it("coverage says answered shares in numbers and words, full text apart from abstracts", async () => {
    panel();
    const table = await screen.findByRole("table", { name: "Coverage: answered per reviewer and item" });
    const row = within(table).getByRole("row", { name: /Statistician/ });
    expect(row).toHaveTextContent("33% answered (2 of 6)");
    expect(row).toHaveTextContent("0% answered (0 of 4)");
    expect(within(table).getByRole("row", { name: /Methodologist/ })).toHaveTextContent("no papers");
  });

  it("lists the widest score spreads, linking to the papers", async () => {
    panel();
    const list = await screen.findByRole("list", { name: "Score dispersion" });
    expect(within(list).getAllByRole("listitem")[0]).toHaveTextContent("spread 50 points");
    expect(within(list).getByRole("link", { name: /Change in CT-Derived FFR/ })).toHaveAttribute("href", "https://europepmc.org/article/MED/35097009");
  });

  it("states the AUC with its interval and that inclusion is not quality", async () => {
    panel();
    const auc = await screen.findByRole("region", { name: "Against SR inclusion" });
    expect(auc).toHaveTextContent("AUC 0.71 (95% CI 0.48–0.94)");
    expect(auc).toHaveTextContent("Inclusion ≠ quality");
  });

  it("explains one model family and links to AI models to mix Claude and Gemini", async () => {
    panel();
    const fam = await screen.findByRole("region", { name: "Model families" });
    expect(fam).toHaveTextContent("All reviewers use one model family (anthropic)");
    expect(within(fam).getByRole("link", { name: /Settings → AI models/ })).toHaveAttribute("href", "/settings/models");
  });

  it("shows rating samples with progress, and admins can create one", async () => {
    const { calls } = panel("admin");
    const ratings = await screen.findByRole("region", { name: "Human reference ratings" });
    expect(await within(ratings).findByText(/1 of 2 papers have 2 raters/)).toBeInTheDocument();
    expect(within(ratings).getByRole("link", { name: /Rate papers/ })).toHaveAttribute("href", `/rate/${SAMPLE_ID}`);
    await userEvent.click(within(ratings).getByRole("button", { name: "Create rating sample" }));
    expect(calls.find((c) => c.method === "POST")).toMatchObject({ path: `/api/v1/evals/${PANEL_ID}/rating-samples`, body: { size: 20, seed: 0 } });
  });

  it("members cannot create samples", async () => {
    panel("member");
    await screen.findByRole("region", { name: "Human reference ratings" });
    expect(screen.queryByRole("button", { name: "Create rating sample" })).not.toBeInTheDocument();
  });

  it("two families: agreement split by family", async () => {
    const metrics = panelMetrics();
    const families = { providers: {}, single_family: false, families: { anthropic: { reviewers: ["methodologist"], fleiss: null, pairwise: {}, reason: "one reviewer" }, google_genai: { reviewers: ["statistician", "clinician"], fleiss: { kappa: 0.3 }, pairwise: {}, reason: null } }, between: {} };
    panel("viewer", panelDetail({ metrics: { ...metrics, panel: { ...metrics.panel, model_families: families } } }));
    const fam = await screen.findByRole("region", { name: "Model families" });
    expect(fam).toHaveTextContent("google_genai");
    expect(fam).toHaveTextContent("0.30");
  });
});

describe("Human reference report", () => {
  it("leads with panel vs human accuracy and kappa per reviewer and item, and Spearman", async () => {
    setup(humanDetail(), "viewer", { "GET /api/v1/rating-samples/:id": { body: ratingSample() } });
    const human = await screen.findByRole("region", { name: "Against human ratings" });
    expect(human).toHaveTextContent("75% (30 of 40)");
    expect(human).toHaveTextContent("2 raters");
    expect(human).toHaveTextContent("85% (34 of 40)");
    const reviewers = within(human).getByRole("table", { name: "Panel vs humans per reviewer" });
    expect(within(reviewers).getByRole("row", { name: /Methodologist/ })).toHaveTextContent("0.55");
    expect(within(human).getByRole("table", { name: "Panel vs humans per item" })).toHaveTextContent("Was the test set split by patient?");
    expect(human).toHaveTextContent("Spearman 0.80");
  });
});

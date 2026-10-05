import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import type { EvalJobOut, EvalSummaryOut } from "../api/types";
import { ABLATION_ID, PANEL_ID, ablationSummary, evalJob, evalSummary, humanSummary, jobOut, panelSummary, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { EvalsHomePage } from "./EvalsHomePage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup({ role = "member", reports = [panelSummary(), ablationSummary(), humanSummary(), evalSummary()], jobs = [evalJob()] }: { role?: "viewer" | "member" | "admin"; reports?: EvalSummaryOut[]; jobs?: EvalJobOut[] } = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/evals": ({ url }) => ({ body: url.searchParams.get("kind") ? reports.filter((r) => r.kind === url.searchParams.get("kind")) : reports }),
    "GET /api/v1/evals/jobs": { body: jobs },
  });
  renderWithProviders(<Routes><Route path="/evals" element={<EvalsHomePage />} /><Route path="/evals/compare" element={<p>compare page</p>} /></Routes>, { route: "/evals" });
  return api;
}

const card = async (name: RegExp) => screen.findByRole("article", { name });

describe("Evals home", () => {
  it("shows a card per report with its kind in words, chips and headline numbers in words", async () => {
    setup();
    const panel = await card(/Review panel · mlffrct-2024/);
    expect(panel).toHaveTextContent("Fleiss kappa 0.42");
    expect(panel).toHaveTextContent("moderate");
    expect(panel).toHaveTextContent("verdict agreement 73%");
    expect(panel).toHaveTextContent("n=10 seed 0");
    expect(within(panel).getByRole("link", { name: /Open report/ })).toHaveAttribute("href", `/evals/${PANEL_ID}`);
    const ablation = await card(/1 \/ 2 \/ 3 reviewers/);
    expect(ablation).toHaveTextContent("Going from 2 to 3 reviewers");
    expect(within(ablation).getByRole("link", { name: /Based on/ })).toHaveAttribute("href", `/evals/${PANEL_ID}`);
    expect(await card(/Human reference/)).toHaveTextContent("75% of answers match");
    expect(await card(/Screening/)).toHaveTextContent("search recall 15 of 16");
  });

  it("lists evaluations in flight with their step and progress", async () => {
    setup();
    const jobs = await screen.findByRole("region", { name: "In progress" });
    expect(jobs).toHaveTextContent("running");
    expect(jobs).toHaveTextContent("step 1 of 3: panel");
    expect(jobs).toHaveTextContent("3 of 10");
  });

  it("shows why an evaluation failed", async () => {
    setup({ jobs: [evalJob({ job: jobOut({ kind: "eval_run", status: "failed", error: "step 'panel' exited with code 1", progress: {} }) })] });
    expect(await screen.findByText(/exited with code 1/)).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "In progress" })).toHaveTextContent("failed");
  });

  it("filters by kind through the API", async () => {
    const { calls } = setup();
    await card(/Review panel/);
    await userEvent.click(screen.getByRole("button", { name: "Human reference" }));
    expect(calls.some((c) => c.path === "/api/v1/evals" && c.search === "?kind=human")).toBe(true);
    expect(await card(/Human reference/)).toBeInTheDocument();
    expect(screen.queryByRole("article", { name: /Screening/ })).not.toBeInTheDocument();
  });

  it("teaches when there is nothing yet, with the way to start", async () => {
    setup({ reports: [], jobs: [] });
    expect(await screen.findByText("No evaluations yet")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "New evaluation" })[0]).toHaveAttribute("href", "/evals/new");
  });

  it("viewers can read but not start evaluations", async () => {
    setup({ role: "viewer" });
    await card(/Review panel/);
    expect(screen.queryByRole("link", { name: "New evaluation" })).not.toBeInTheDocument();
  });

  it("compares 2 reports of one family, and says why mixed families cannot be compared", async () => {
    setup();
    await card(/Review panel/);
    const compare = () => screen.getByRole("button", { name: /^Compare/ });
    await userEvent.click(screen.getByRole("checkbox", { name: /Select Review panel · mlffrct-2024/ }));
    expect(compare()).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Select Human reference/ }));
    expect(compare()).toBeEnabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /Select 1 \/ 2 \/ 3 reviewers/ }));
    expect(compare()).toBeDisabled();
    expect(screen.getByRole("region", { name: "Compare" })).toHaveTextContent("same family");
    await userEvent.click(screen.getByRole("checkbox", { name: /Select 1 \/ 2 \/ 3 reviewers/ }));
    await userEvent.click(compare());
    expect(await screen.findByText("compare page")).toBeInTheDocument();
    expect(ABLATION_ID).toBeTruthy();
  });
});

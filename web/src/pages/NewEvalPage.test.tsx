import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { JOB_ID, PANEL_ID, estimateOut, goldSet, jobOut, panelSummary, reviewSettings, runOut, session } from "../test/fixtures";
import { mockApi, type MockHandler } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { NewEvalPage } from "./NewEvalPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(extra: Record<string, MockHandler> = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session("member") },
    "GET /api/v1/gold-sets": { body: [goldSet(), goldSet({ id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", name: "broken", usable: false })] },
    "GET /api/v1/runs": { body: [runOut({ kind: "research" })] },
    "GET /api/v1/evals": { body: [panelSummary()] },
    "GET /api/v1/settings/review": { body: reviewSettings() },
    "POST /api/v1/evals/estimate": { body: estimateOut() },
    "POST /api/v1/evals": { status: 202, body: jobOut({ kind: "eval_run", run_id: null }) },
    "GET /api/v1/jobs/:id": { body: jobOut({ kind: "eval_run", status: "done", progress: { status: "done", result: { eval_id: PANEL_ID } } }) },
    ...extra,
  });
  renderWithProviders(<Routes><Route path="/evals/new" element={<NewEvalPage />} /></Routes>, { route: "/evals/new" });
  return api;
}

const choose = async (kind: RegExp) => userEvent.click(await screen.findByRole("radio", { name: kind }));

describe("New evaluation", () => {
  it("panel: inputs, estimate in words, start, follow, open the report", async () => {
    const { calls } = setup();
    await choose(/Review panel/);
    const gold = await screen.findByLabelText("Gold set");
    expect(within(gold).queryByRole("option", { name: /broken/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(gold, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
    await userEvent.clear(screen.getByLabelText("Papers to sample"));
    await userEvent.type(screen.getByLabelText("Papers to sample"), "12");
    expect(screen.getByText(/current review settings, version 3/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start evaluation" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    const estimate = await screen.findByRole("region", { name: "Cost estimate" });
    expect(estimate).toHaveTextContent("40 model calls");
    expect(estimate).toHaveTextContent("100,000 input tokens");
    expect(estimate).toHaveTextContent("unknown price");
    expect(estimate).toHaveTextContent("Upper bound");
    const sent = calls.find((c) => c.path === "/api/v1/evals/estimate")!.body;
    expect(sent).toMatchObject({ kind: "panel", mode: "live", gold_set_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", sample: 12, seed: 0 });
    await userEvent.click(screen.getByRole("button", { name: "Start evaluation" }));
    expect(calls.find((c) => c.method === "POST" && c.path === "/api/v1/evals")!.body).toEqual(sent);
    expect(await screen.findByRole("link", { name: "Open report" })).toHaveAttribute("href", `/evals/${PANEL_ID}`);
    expect(calls.some((c) => c.path === `/api/v1/jobs/${JOB_ID}`)).toBe(true);
  });

  it("panel from a finished run instead of a gold set", async () => {
    const { calls } = setup();
    await choose(/Review panel/);
    await userEvent.click(await screen.findByRole("radio", { name: /A finished run/ }));
    await userEvent.selectOptions(await screen.findByLabelText("Run"), runOut().id);
    await userEvent.click(screen.getByRole("checkbox", { name: /Demo mode/ }));
    await userEvent.click(screen.getByRole("button", { name: "Start evaluation" }));
    const body = calls.find((c) => c.method === "POST" && c.path === "/api/v1/evals")!.body;
    expect(body).toMatchObject({ kind: "panel", mode: "demo", run_id: runOut().id });
    expect(body).not.toHaveProperty("gold_set_id");
  });

  it("ablation: picks a panel report and can re-run the editor", async () => {
    const { calls } = setup();
    await choose(/1 \/ 2 \/ 3 reviewers/);
    await userEvent.selectOptions(await screen.findByLabelText("Panel report"), PANEL_ID);
    await userEvent.click(screen.getByRole("checkbox", { name: /Re-run the editor/ }));
    await userEvent.click(screen.getByRole("button", { name: "Estimate cost" }));
    await screen.findByRole("region", { name: "Cost estimate" });
    expect(calls.find((c) => c.path === "/api/v1/evals/estimate")!.body).toMatchObject({ kind: "ablation", panel_eval_id: PANEL_ID, rerun_editor: true });
  });

  it("human reference explains where it comes from instead of starting a job", async () => {
    setup();
    await choose(/Human reference/);
    expect(screen.getByText(/recomputed each time someone submits ratings/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start evaluation" })).not.toBeInTheDocument();
  });

  it("says what is missing instead of sending an incomplete request", async () => {
    const { calls } = setup();
    await choose(/Screening/);
    await userEvent.click(await screen.findByRole("button", { name: "Estimate cost" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a gold set.");
    expect(calls.some((c) => c.path === "/api/v1/evals/estimate")).toBe(false);
  });

  it("builds a gold set from a systematic review", async () => {
    const { calls } = setup({ "POST /api/v1/gold-sets": { status: 202, body: jobOut({ kind: "gold_build", run_id: null }) } });
    await choose(/Screening/);
    await userEvent.click(screen.getByText("Build a gold set from a systematic review"));
    const form = screen.getByRole("group", { name: "New gold set" });
    await userEvent.type(within(form).getByLabelText("Name"), "my-sr");
    await userEvent.type(within(form).getByLabelText(/Citation/), "Doe 2025");
    await userEvent.type(within(form).getByLabelText("Topic"), "AI CT");
    await userEvent.type(within(form).getByLabelText(/Search query/), "ct AND ai");
    await userEvent.type(within(form).getByLabelText(/Included studies/), "10.1/x | Study | 2020");
    await userEvent.click(within(form).getByRole("button", { name: "Build gold set" }));
    expect(calls.find((c) => c.path === "/api/v1/gold-sets" && c.method === "POST")!.body).toMatchObject({
      name: "my-sr", citation: "Doe 2025", topic: "AI CT", query: "ct AND ai", included: [{ doi: "10.1/x", title: "Study", year: "2020" }],
    });
    expect(await within(form).findByRole("status")).toHaveTextContent(/done/);
  });
});

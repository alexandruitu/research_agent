import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RunDetailOut } from "../api/types";
import { jobOut, RUN_ID, runDetail, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { RunDetailPage } from "./RunDetailPage";

afterEach(() => vi.unstubAllGlobals());

const ME = "11111111-1111-4111-8111-111111111111";
const detail = (over: Partial<RunDetailOut> = {}): RunDetailOut => runDetail({
  kind: "research", name: "Baseline", note: "first live try", created_by: ME, created_by_name: "Member", status: "done",
  config: {
    field_id: "44444444-4444-4444-8444-444444444444", field_name: "ML CT-FFR", field_version: 2, topic: "ct-ffr", sources: [{ name: "europepmc", max_results: 50 }],
    settings_version: 3, panel: [{ key: "methodologist", name: "Methodologist", version: 2 }], models: { screen: "anthropic:claude-sonnet-5" },
    mode: "live", max_papers: 5, prompt_version: "m1.3", jev: true,
  },
  timeline: { stages: [{ name: "plan", status: "completed", started_at: "2026-10-06T10:00:00Z", finished_at: "2026-10-06T10:00:12Z", seconds: 12 }], started_at: "2026-10-06T10:00:00Z", updated_at: "2026-10-06T10:05:00Z", status: "completed", recorded: true },
  wall_seconds: 300, resume: { allowed: false, code: "not_resumable", reason: "Only a failed or cancelled run can be resumed" },
  links: { papers: `/?run=${RUN_ID}`, evals: [], library_count: 2 }, can_manage: true, active_job_id: null, ...over,
});

const CALLS = { recorded: true, estimate: true, rows: [{ stage: "screen", role: "screen", model: "anthropic:claude-sonnet-5", provider: "anthropic", calls: 4, input_chars: 8000, output_chars: 900, cost_usd: 0.012, cache_hits: null, seconds: null }], providers: [{ provider: "anthropic", calls: 4, cost_usd: 0.012 }], totals: { calls: 4, cost_usd: 0.012, unpriced_models: [] } };

function setup(role: "viewer" | "member" = "member", data = detail(), extra: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/runs/:id": { body: data },
    "GET /api/v1/runs/:id/calls": { body: CALLS },
    "GET /api/v1/runs/:id/log": { body: { exists: true, size: 40, text: "plan: start\nkey ***\n", truncated: false, failed_stage: null, reason: null, attempts: [] } },
    ...extra,
  });
  renderWithProviders(<Routes><Route path="/runs/:runId" element={<RunDetailPage />} /><Route path="/runs" element={<p>runs list</p>} /></Routes>, { route: `/runs/${RUN_ID}` });
  return api;
}

describe("run detail", () => {
  it("says in one line what the run searched, skipped, capped and read", async () => {
    setup("member", detail({ coverage: { searched: ["europepmc"], skipped: [{ source: "semantic_scholar", error_type: "x", reason: "rate limited (HTTP 429)", detail: "" }], max_papers: 12, full_text: 3, abstract_only: 7 } }));
    expect(await screen.findByText("Searched: Europe PMC · Skipped: Semantic Scholar (rate limited) · Max papers: 12 · Text: 3 full text / 7 abstract only")).toBeInTheDocument();
  });

  it("shows the name, note, frozen configuration, stage times, counts and cost estimate", async () => {
    setup();
    expect(await screen.findByRole("heading", { level: 1, name: "Baseline" })).toBeInTheDocument();
    expect(screen.getByText("first live try")).toBeInTheDocument();
    const config = screen.getByRole("region", { name: "Frozen configuration" });
    expect(config).toHaveTextContent("ML CT-FFR · version 2");
    expect(config).toHaveTextContent("europepmc (up to 50)");
    expect(config).toHaveTextContent("Methodologist v2");
    expect(config).toHaveTextContent("m1.3");
    expect(screen.getByRole("region", { name: "Stages" })).toHaveTextContent("12 s");
    expect(screen.getByRole("region", { name: "Results" })).toHaveTextContent("5 min 0 s");
    const calls = screen.getByRole("region", { name: /Model calls and cost/ });
    await waitFor(() => expect(calls).toHaveTextContent("4 distinct calls"));
    expect(calls).toHaveTextContent("estimate");
    expect(screen.getByRole("link", { name: "2 saved to the library" })).toBeInTheDocument();
  });

  it("explains a refused resume and offers to run again with the same configuration", async () => {
    const { calls } = setup("member", detail({ status: "failed", error: "failed at stage 'screen': X", resume: { allowed: false, code: "prompt_version_changed", reason: "The prompts changed since this run started (m1.2 → m1.3)" } }), {
      "POST /api/v1/runs/:id/rerun": { status: 202, body: { job: jobOut(), run_id: RUN_ID } },
    });
    const note = await screen.findByRole("note");
    expect(note).toHaveTextContent("The prompts changed");
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
    await userEvent.click(within(note).getByRole("button", { name: "Run again (same configuration)" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/rerun"))).toBe(true));
  });

  it("cancels a running run after confirming", async () => {
    const { calls } = setup("member", detail({ status: "running", active_job_id: "55555555-5555-4555-8555-555555555555" }), {
      "POST /api/v1/runs/:id/cancel": { status: 202, body: { status: "cancelling" } },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Cancel run…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel run" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/cancel"))).toBe(true));
    expect(await screen.findByText(/checkpoint is kept/)).toBeInTheDocument();
  });

  it("deleting from the page goes back to the list", async () => {
    setup("member", detail(), { "DELETE /api/v1/runs/:id": { body: { id: RUN_ID, folder: "trashed" } } });
    await userEvent.click(await screen.findByRole("button", { name: "More actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete…" }));
    await userEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete run" }));
    expect(await screen.findByText("runs list")).toBeInTheDocument();
  });

  it("members read the redacted log on demand; viewers see neither log nor calls", async () => {
    setup();
    await userEvent.click(await screen.findByText(/Show the last 300 lines/));
    expect(await screen.findByLabelText("Worker log")).toHaveTextContent("key ***");
    expect(screen.getByRole("link", { name: "Download the log" })).toHaveAttribute("href", `/api/v1/runs/${RUN_ID}/log?download=true`);
  });

  it("viewers get no log, no calls and no management actions", async () => {
    setup("viewer", detail({ can_manage: false, created_by: "someone-else" }));
    await screen.findByRole("heading", { level: 1 });
    expect(screen.queryByRole("region", { name: "Worker log" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /Model calls/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Run again/ })).not.toBeInTheDocument();
  });
});

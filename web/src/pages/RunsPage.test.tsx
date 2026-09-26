import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { fieldOut, FIELD_ID, JOB_ID, jobOut, RUN_ID, runOut, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { RunsPage } from "./RunsPage";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const FAILED = runOut({ id: "88888888-8888-4888-8888-888888888888", kind: "research", status: "failed", gold_set_name: null, paper_count: 0, error: "failed at stage 'screen': ValidationError: Etapa nu s-a încheiat." });

function setup(role: "viewer" | "member" = "member", extra: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/runs": { body: [FAILED, runOut()] },
    "GET /api/v1/fields": { body: [fieldOut()] },
    ...extra,
  });
  renderWithProviders(<RunsPage />);
  return api;
}

describe("RunsPage list", () => {
  it("lists runs with a status in words", async () => {
    setup("viewer");
    const table = await screen.findByRole("table");
    expect(within(table).getByText("failed")).toBeInTheDocument();
    expect(within(table).getByText("done")).toBeInTheDocument();
    expect(within(table).getByText("mlffrct-2024")).toBeInTheDocument();
    expect(within(table).getAllByRole("link", { name: /See papers/ })[1]).toHaveAttribute("href", `/?run=${RUN_ID}`);
  });

  it("viewers do not get the start form", async () => {
    setup("viewer");
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: "Start run" })).not.toBeInTheDocument();
  });

  it("a failed run shows why and offers Resume to members only", async () => {
    setup("member");
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("failed at stage 'screen'");
    expect(within(banner).getByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("viewers see the reason but no Resume button", async () => {
    setup("viewer");
    expect(await screen.findByRole("alert")).toHaveTextContent("failed at stage 'screen'");
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("says so when there are no runs", async () => {
    setup("viewer", { "GET /api/v1/runs": { body: [] } });
    expect(await screen.findByText("No runs yet.")).toBeInTheDocument();
  });
});

describe("starting and following a run", () => {
  it("posts the field and the cap with an idempotency key and shows the job", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/runs": { status: 202, body: { job: jobOut(), run_id: RUN_ID } },
      [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "running", progress: { status: "running", stages: { plan: "completed", search: "running" } } }) },
    });
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.clear(screen.getByLabelText("Papers to screen"));
    await userEvent.type(screen.getByLabelText("Papers to screen"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    const post = calls.find((c) => c.method === "POST" && c.path === "/api/v1/runs")!;
    expect(post.body).toEqual({ field_id: FIELD_ID, max_papers: 5, mode: "live" });
    expect(post.headers.get("Idempotency-Key")).toBeTruthy();
    const progress = await screen.findByRole("status", { name: "Run progress" });
    await waitFor(() => expect(progress).toHaveTextContent("running"));
    expect(progress).toHaveTextContent("plan: completed");
    expect(progress).toHaveTextContent("search: running");
  });

  it("refreshes the run list when the job finishes", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/runs": { status: 202, body: { job: jobOut(), run_id: RUN_ID } },
      [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "done" }) },
    });
    await screen.findByRole("table");
    const before = calls.filter((c) => c.method === "GET" && c.path === "/api/v1/runs").length;
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && c.path === "/api/v1/runs").length).toBeGreaterThan(before + 1));
  });

  it("the demo box switches the mode", async () => {
    const { calls } = setup("member", { "POST /api/v1/runs": { status: 202, body: { job: jobOut({ status: "done" }), run_id: RUN_ID } }, [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "done" }) } });
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.click(screen.getByLabelText(/Demo mode/));
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/api/v1/runs")?.body).toMatchObject({ mode: "demo" }));
  });

  it("refuses a cap outside 1 to 12 before calling the server", async () => {
    const { calls } = setup();
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.clear(screen.getByLabelText("Papers to screen"));
    await userEvent.type(screen.getByLabelText("Papers to screen"), "13");
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText("Choose between 1 and 12 papers.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the server's reason when it refuses (too many active runs)", async () => {
    setup("member", { "POST /api/v1/runs": { status: 429, body: { code: "too_many_active_runs", message: "You already have the maximum number of active runs", request_id: "r-1" } } });
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText(/maximum number of active runs/)).toBeInTheDocument();
  });

  it("a failed job shows its stored error", async () => {
    setup("member", {
      "POST /api/v1/runs": { status: 202, body: { job: jobOut(), run_id: RUN_ID } },
      [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "failed", error: "failed at stage 'search': HTTPError: 503" }) },
    });
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    const progress = await screen.findByRole("status", { name: "Run progress" });
    await waitFor(() => expect(progress).toHaveTextContent("failed at stage 'search'"));
  });
});

describe("resume", () => {
  it("resumes the failed run and follows the new job", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/runs/:id/resume": { status: 202, body: { job: jobOut(), run_id: FAILED.id } },
      [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "running" }) },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));
    await screen.findByRole("status", { name: "Run progress" });
    expect(calls.some((c) => c.method === "POST" && c.path === `/api/v1/runs/${FAILED.id}/resume`)).toBe(true);
  });

  it("explains a refused resume", async () => {
    setup("member", { "POST /api/v1/runs/:id/resume": { status: 409, body: { code: "conflict", message: "Only a failed research run can be resumed", request_id: "r-2" } } });
    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));
    expect(await screen.findByText(/Only a failed research run can be resumed/)).toBeInTheDocument();
  });
});

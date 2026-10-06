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

const ME = "11111111-1111-4111-8111-111111111111";
const FAILED = runOut({ id: "88888888-8888-4888-8888-888888888888", kind: "research", status: "failed", gold_set_name: null, paper_count: 0, error: "failed at stage 'screen': ValidationError: Etapa nu s-a încheiat.", created_by: ME, created_by_name: "Member", topic: "ct-ffr" });

function setup(role: "viewer" | "member" = "member", extra: Parameters<typeof mockApi>[0] = {}, route = "/runs") {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/runs": { body: [FAILED, runOut()] },
    "GET /api/v1/fields": { body: [fieldOut()] },
    ...extra,
  });
  renderWithProviders(<RunsPage />, { route });
  return api;
}

describe("RunsPage list", () => {
  it("each run row explains its coverage on hover, focus or tap", async () => {
    setup("viewer", { "GET /api/v1/runs": { body: [runOut({ coverage: { searched: ["europepmc", "openalex"], skipped: [], max_papers: 12, full_text: 3, abstract_only: 7 } })] } });
    const trigger = await screen.findByRole("button", { name: /coverage of/ });
    await userEvent.click(trigger);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Searched: Europe PMC, OpenAlex · Skipped: none · Max papers: 12 · Text: 3 full text / 7 abstract only");
  });

  it("lists runs with a status in words, a link to each run and its papers", async () => {
    setup("viewer");
    const table = await screen.findByRole("table");
    expect(within(table).getByText("failed")).toBeInTheDocument();
    expect(within(table).getByText("done")).toBeInTheDocument();
    expect(within(table).getByText(/mlffrct-2024/)).toBeInTheDocument();
    expect(within(table).getAllByRole("link", { name: /^Papers/ })[1]).toHaveAttribute("href", `/?run=${RUN_ID}`);
    expect(within(table).getAllByRole("link", { name: "ML CT-FFR" })[0]).toHaveAttribute("href", `/runs/${FAILED.id}`);
    expect(within(table).getByText("Failed at screen (ValidationError)")).toHaveAttribute("title", expect.stringMatching(/Etapa nu s-a încheiat/));
  });

  it("names a run by its own name and marks pinned runs and cancelled status in words", async () => {
    setup("viewer", { "GET /api/v1/runs": { body: [runOut({ kind: "research", name: "Baseline", pinned: true, status: "cancelled", note: "first try" })] } });
    const table = await screen.findByRole("table");
    expect(within(table).getByRole("link", { name: "Baseline" })).toBeInTheDocument();
    expect(within(table).getByText("pinned")).toBeInTheDocument();
    expect(within(table).getByText("cancelled")).toBeInTheDocument();
    expect(within(table).getByText("first try")).toBeInTheDocument();
  });

  it("viewers get no start form and a menu with only Open and Export", async () => {
    setup("viewer");
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: "Start run" })).not.toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: /Actions for ML CT-FFR/ })[0]!);
    const menu = screen.getByRole("menu");
    expect(within(menu).getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Open", "Export CSV", "Export bundle (zip)"]);
  });

  it("the creator's menu offers resume, rename, pin and delete for a failed run", async () => {
    setup("member");
    await screen.findByRole("table");
    await userEvent.click(screen.getAllByRole("button", { name: /Actions for ML CT-FFR/ })[0]!);
    const names = within(screen.getByRole("menu")).getAllByRole("menuitem").map((i) => i.textContent);
    expect(names).toEqual(expect.arrayContaining(["Resume", "Run again (same configuration)", "Run again with current settings", "Rename or add a note…", "Pin to top", "Delete…"]));
  });

  it("sends the filters to the server and keeps them in the URL", async () => {
    const { calls } = setup("member");
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Status"), "cancelled");
    await userEvent.click(screen.getByLabelText(/Only mine/));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/runs" && c.search.includes("status=cancelled") && c.search.includes("mine=true"))).toBe(true));
    expect(screen.getByRole("button", { name: "Clear all" })).toBeInTheDocument();
  });

  it("says so when there are no runs", async () => {
    setup("viewer", { "GET /api/v1/runs": { body: [] } });
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
  });
});

describe("bulk actions", () => {
  it("two selected runs can be compared; deleting asks first and reports refusals", async () => {
    const mine = runOut({ id: "99999999-9999-4999-8999-999999999999", kind: "research", created_by: ME, field_name: "Other" });
    const { calls } = setup("member", {
      "GET /api/v1/runs": { body: [FAILED, mine] },
      "POST /api/v1/runs/delete": { body: { deleted: [FAILED.id], refused: [{ id: mine.id, code: "referenced_by_eval", message: "1 evaluation report(s) were computed from this run" }] } },
    });
    await screen.findByRole("table");
    await userEvent.click(screen.getByLabelText("Select every run shown"));
    const bar = screen.getByRole("region", { name: "Selected runs" });
    expect(within(bar).getByRole("link", { name: "Compare" })).toHaveAttribute("href", `/runs/compare?ids=${FAILED.id},${mine.id}`);
    await userEvent.click(within(bar).getByRole("button", { name: /Delete/ }));
    const dialog = screen.getByRole("alertdialog", { name: "Delete 2 runs?" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete 2 runs" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/api/v1/runs/delete")?.body).toEqual({ ids: [FAILED.id, mine.id] }));
    const notes = screen.getByRole("region", { name: "Notifications" });
    await waitFor(() => expect(notes).toHaveTextContent("its folder is in the trash"));
    expect(notes).toHaveTextContent("evaluation report");
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

  it("preselects the field from the URL and names fields with their version", async () => {
    setup("member", { "GET /api/v1/fields": { body: [{ ...fieldOut(), current_version: 3 }] } }, `/runs?field=${FIELD_ID}`);
    const select = await screen.findByLabelText("Field");
    expect(select).toHaveValue(FIELD_ID);
    expect(within(select).getByRole("option", { name: "ML CT-FFR · v3" })).toBeInTheDocument();
  });

  it("explains a field whose sources are all disabled", async () => {
    setup("member", { "POST /api/v1/runs": { status: 422, body: { code: "no_enabled_source", message: "None of this field's sources is enabled", request_id: "r" } } }, `/runs?field=${FIELD_ID}`);
    await userEvent.click(await screen.findByRole("button", { name: "Start run" }));
    expect(await screen.findByText(/Settings → Sources/)).toHaveClass("form-error");
  });

  it("shows the refusal for an archived field", async () => {
    setup("member", { "POST /api/v1/runs": { status: 409, body: { code: "archived", message: "This field is archived; restore it first", request_id: "r" } } }, `/runs?field=${FIELD_ID}`);
    await userEvent.click(await screen.findByRole("button", { name: "Start run" }));
    expect(await screen.findByText("This field is archived; restore it first")).toHaveAttribute("role", "alert");
  });
});

describe("resume", () => {
  it("resumes the failed run from the row menu", async () => {
    const { calls } = setup("member", { "POST /api/v1/runs/:id/resume": { status: 202, body: { job: jobOut(), run_id: FAILED.id } } });
    await screen.findByRole("table");
    await userEvent.click(screen.getAllByRole("button", { name: /Actions for ML CT-FFR/ })[0]!);
    await userEvent.click(screen.getByRole("menuitem", { name: "Resume" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.path === `/api/v1/runs/${FAILED.id}/resume`)).toBe(true));
    expect(await screen.findByText(/Resuming/)).toBeInTheDocument();
  });

  it("when the prompts changed, offers to run it again with the same configuration", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/runs/:id/resume": { status: 409, body: { code: "prompt_version_changed", message: "The prompts changed since this run started", request_id: "r-2" } },
      "POST /api/v1/runs/:id/rerun": { status: 202, body: { job: jobOut(), run_id: RUN_ID } },
    });
    await screen.findByRole("table");
    await userEvent.click(screen.getAllByRole("button", { name: /Actions for ML CT-FFR/ })[0]!);
    await userEvent.click(screen.getByRole("menuitem", { name: "Resume" }));
    await userEvent.click(await screen.findByRole("button", { name: "Run again (same configuration)" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path.endsWith("/rerun"))?.body).toEqual({ config: "same" }));
  });
});

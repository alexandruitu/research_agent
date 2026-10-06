import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { lostRow, paperRow, runDetail, runOut, session, STAGES, RUN_ID, versionOut } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { PapersPage } from "./PapersPage";

/** Most tests here cover the Detailed view (the full table); the Simple view has its own tests below. */
beforeEach(() => localStorage.setItem("papers.view.11111111-1111-4111-8111-111111111111", "detailed"));
afterEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function Location() {
  const location = useLocation();
  return <output aria-label="location">{location.search}</output>;
}

const page = (items: unknown[], total = items.length, extra: Record<string, unknown> = {}) => ({ items, total, page: 1, page_size: 25, ...extra });

/** These tests cover the flat list (Group by: None); the grouped view has its own tests (features/papers/groups.test.tsx). */
const flat = (route: string) => route + (route.includes("?") ? "&" : "?") + "group=none";

function setup(handlers: Parameters<typeof mockApi>[0] = {}, route = "/") {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session("member") },
    "GET /api/v1/runs": { body: [runOut({ id: "99999999-9999-4999-8999-999999999999", paper_count: 0, gold_set_name: null, kind: "research" }), runOut()] },
    "GET /api/v1/runs/:id": { body: runDetail() },
    "GET /api/v1/stages": { body: STAGES },
    "GET /api/v1/runs/:id/papers": { body: page([paperRow(), lostRow()], 2) },
    ...handlers,
  });
  renderWithProviders(
    <>
      <Routes><Route path="/" element={<PapersPage />} /></Routes>
      <Location />
    </>,
    { route: flat(route) },
  );
  return api;
}

describe("PapersPage", () => {
  it("opens on the first run that has papers and lists them with one column group per stage", async () => {
    const { calls } = setup();
    expect(await screen.findByText("Change in CT-Derived FFR Across the Lesion Improve the Diagnostic Performance")).toBeInTheDocument();
    expect(calls.some((c) => c.path === `/api/v1/runs/${RUN_ID}/papers`)).toBe(true);
    expect(screen.getByText(/151 screened/)).toBeInTheDocument();
    expect(screen.getByText(/112 kept/)).toHaveTextContent("16 in the SR");
    expect(screen.getByRole("button", { name: "In the SR" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Not in the SR" })).toBeInTheDocument();
  });

  it("for a run without a gold set, omits the SR count and the SR chips and never sends in_sr", async () => {
    const research = runOut({ kind: "research", gold_set_name: null, paper_count: 10 });
    const { calls } = setup(
      {
        "GET /api/v1/runs": { body: [research] },
        "GET /api/v1/runs/:id": { body: runDetail({ ...research, counts: { screened: 10, kept: 6, dropped: 4, escalated: 2, in_sr: null } }) },
        "GET /api/v1/runs/:id/papers": { body: page([paperRow({ in_sr: null })], 1) },
      },
      "/?in_sr=true",
    );
    await screen.findByRole("table");
    expect(await screen.findByText(/10 screened/)).not.toHaveTextContent("in the SR");
    expect(screen.queryByRole("button", { name: "In the SR" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Not in the SR" })).not.toBeInTheDocument();
    const paperCalls = calls.filter((c) => c.path.endsWith("/papers"));
    expect(paperCalls.length).toBeGreaterThan(0);
    expect(paperCalls.every((c) => !new URLSearchParams(c.search).has("in_sr"))).toBe(true);
  });

  it("labels every stage with its status in words and only measured stages look measured", async () => {
    setup();
    await screen.findByRole("table");
    const strip = screen.getAllByRole("button", { name: /^(Search|Screen|Extract|Review panel|Rank)/ });
    const status = (label: RegExp) => strip.find((b) => label.test(b.textContent ?? ""))!;
    expect(status(/Search/)).toHaveAttribute("data-status", "measured");
    expect(status(/Screen/)).toHaveAttribute("data-status", "measured");
    expect(status(/Review panel/)).toHaveAttribute("data-status", "caveat");
    expect(status(/Review panel/)).toHaveTextContent("one model family");
    expect(status(/Rank/)).toHaveAttribute("data-status", "unmeasured");
    expect(status(/Rank/)).toHaveTextContent("not measured");
    expect(status(/Search/)).toHaveTextContent("recall 15/16");
  });

  it("shows not-applicable and missing differently, and the SR label in words", async () => {
    setup({ "GET /api/v1/runs/:id/papers": { body: page([paperRow({ extract: { missing: true } }), lostRow()], 2) } });
    const table = await screen.findByRole("table");
    expect(within(table).getByText("missing")).toBeInTheDocument();
    expect(within(table).getAllByLabelText("not applicable").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("yes").length).toBe(2);
  });

  it("a filter chip changes the request, the URL and goes back to page 1", async () => {
    const { calls } = setup(
      { "GET /api/v1/runs/:id/papers": ({ url }) => ({ body: url.searchParams.get("decision") === "exclude" ? page([lostRow()], 1) : page([paperRow(), lostRow()], 60) }) },
      "/?page=2",
    );
    await screen.findByRole("table");
    await userEvent.click(screen.getByRole("button", { name: "Dropped" }));
    expect(await screen.findByRole("button", { name: "Dropped" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("location")).toHaveTextContent("decision=exclude");
    expect(screen.getByLabelText("location")).not.toHaveTextContent("page=");
    const last = calls.filter((c) => c.path.endsWith("/papers")).at(-1)!;
    expect(new URLSearchParams(last.search).get("decision")).toBe("exclude");
    expect(new URLSearchParams(last.search).get("page")).toBe("1");
    await userEvent.click(screen.getByRole("button", { name: "Dropped" })); // toggles off
    expect(screen.getByLabelText("location")).not.toHaveTextContent("decision=");
  });

  it("sorting by topic match toggles ascending and descending and sets aria-sort", async () => {
    const { calls } = setup();
    await screen.findByRole("table");
    const header = screen.getByRole("columnheader", { name: /Criteria/ });
    await userEvent.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "ascending");
    await userEvent.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "descending");
    const last = calls.filter((c) => c.path.endsWith("/papers")).at(-1)!;
    expect(new URLSearchParams(last.search).get("sort")).toBe("criterion:topic_match");
    expect(new URLSearchParams(last.search).get("direction")).toBe("desc");
  });

  it("pages forward and back and disables the buttons at the ends", async () => {
    const { calls } = setup({ "GET /api/v1/runs/:id/papers": ({ url }) => ({ body: page([paperRow()], 60, { page: Number(url.searchParams.get("page") ?? 1) }) }) });
    await screen.findByRole("table");
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    expect(new URLSearchParams(calls.filter((c) => c.path.endsWith("/papers")).at(-1)!.search).get("page")).toBe("2");
  });

  it("says so when nothing matches", async () => {
    setup({ "GET /api/v1/runs/:id/papers": { body: page([], 0) } }, "/?decision=exclude");
    expect(await screen.findByText("No papers match these filters")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Clear all filters" })).toBeInTheDocument();
  });

  it("shows active filters as chips; one removes its filter, Clear all removes them all", async () => {
    setup({}, "/?decision=exclude&escalated=true&src=openalex");
    const chips = await screen.findByRole("group", { name: "Active filters" });
    expect(within(chips).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Dropped × (remove filter)", "Only escalated × (remove filter)", "Source: OpenAlex × (remove filter)", "Clear all",
    ]);
    await userEvent.click(within(chips).getByRole("button", { name: /Only escalated/ }));
    expect(screen.getByLabelText("location")).not.toHaveTextContent("escalated");
    await userEvent.click(within(screen.getByRole("group", { name: "Active filters" })).getByRole("button", { name: "Clear all" }));
    expect(screen.queryByRole("group", { name: "Active filters" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("location").textContent).toBe("?group=none"); // Clear all keeps the grouping
  });

  it("keyboard: j moves to a paper, o opens it, x selects it, ? lists the shortcuts", async () => {
    setup({ "GET /api/v1/runs/:id/papers/:id": { status: 404, body: { code: "not_found", message: "x", request_id: "r" } } });
    await screen.findByText(/Diagnostic accuracy/);
    await userEvent.keyboard("j");
    expect(screen.getByRole("button", { name: /Diagnostic accuracy/ })).toHaveFocus();
    await userEvent.keyboard("j");
    expect(screen.getByRole("button", { name: /Change in CT-Derived/ })).toHaveFocus();
    await userEvent.keyboard("x");
    expect(screen.getByRole("region", { name: "Selection" })).toHaveTextContent("1 selected");
    await userEvent.keyboard("o");
    expect(screen.getByLabelText("location")).toHaveTextContent("paper=55555555");
    await userEvent.keyboard("?");
    expect(screen.getByRole("dialog", { name: "Papers shortcuts" })).toBeInTheDocument();
  });

  it("shows the request id when the table cannot be loaded", async () => {
    setup({ "GET /api/v1/runs/:id/papers": { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "req-7" } } });
    expect(await screen.findByRole("alert")).toHaveTextContent("req-7");
  });

  it("asks for a run when there is none", async () => {
    setup({ "GET /api/v1/runs": { body: [] } });
    expect(await screen.findByRole("heading", { name: "Create your first field in 3 steps" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create your first field" })).toHaveAttribute("href", "/fields/new");
  });

  it("filters by the deciding criterion and by source, naming criteria from the run's field version", async () => {
    const { calls } = setup({
      "GET /api/v1/runs": { body: [runOut({ field_version: 2 })] },
      "GET /api/v1/fields/:id/versions/2": { body: versionOut() },
    });
    await screen.findByRole("table");
    expect(screen.getByRole("combobox", { name: "Run" })).toHaveTextContent("ML CT-FFR · v2 · eval");
    const by = await screen.findByRole("combobox", { name: "Dropped by criterion" });
    await within(by).findByRole("option", { name: /excl 1: The paper is a review/ });
    await userEvent.selectOptions(by, "e1");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Source" }), "openalex");
    const last = new URLSearchParams(calls.filter((c) => c.path.endsWith("/papers")).at(-1)!.search);
    expect(last.get("decided_by")).toBe("e1");
    expect(last.get("source")).toBe("openalex");
    expect(screen.queryByLabelText(/Topic match from/)).not.toBeInTheDocument();
  });
});

describe("PapersPage · peer-review columns", () => {
  const panelRow = () => paperRow({ score: 72.4, coverage: 0.8, red_flag_count: 2, text_source: "pmc_oa" });
  const abstractRow = () => ({ ...lostRow(), score: null, coverage: 0.3, red_flag_count: 0, text_source: "abstract" });

  it("shows the panel score with coverage in words, red flags and the text reviewed", async () => {
    setup({ "GET /api/v1/runs/:id/papers": { body: page([panelRow(), abstractRow()], 2) } });
    const rows = await screen.findAllByRole("row");
    const first = rows.find((r) => r.textContent?.includes("Diagnostic accuracy"))!;
    expect(first).toHaveTextContent("72 · 8/10 answered");
    expect(within(first).getByRole("meter", { name: "coverage 80%" })).toBeInTheDocument();
    expect(first).toHaveTextContent("⚑ 2 red flags");
    expect(first).toHaveTextContent("full text · PMC");
    const second = rows.find((r) => r.textContent?.includes("Change in CT-Derived"))!;
    expect(second).toHaveTextContent("no score · 3/10 answered");
    expect(second).toHaveTextContent("abstract only");
    expect(second).toHaveTextContent("none");
    expect(screen.getByRole("columnheader", { name: /Peer review score/ })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Reviewers A / B" })).not.toBeInTheDocument();
  });

  it("filters to papers with red flags, and the filter lives in the URL", async () => {
    const { calls } = setup({ "GET /api/v1/runs/:id/papers": { body: page([panelRow()], 1) } });
    await userEvent.click(await screen.findByRole("button", { name: "Has red flags" }));
    expect(screen.getByLabelText("location")).toHaveTextContent("flags=true");
    expect(calls.some((c) => c.path.endsWith("/papers") && c.search.includes("has_red_flags=true"))).toBe(true);
    expect(screen.getByRole("button", { name: "Has red flags" })).toHaveAttribute("aria-pressed", "true");
  });

  it("sorts by the panel score", async () => {
    const { calls } = setup({ "GET /api/v1/runs/:id/papers": { body: page([panelRow()], 1) } });
    await userEvent.click(await screen.findByRole("button", { name: /Peer review score/ }));
    expect(calls.some((c) => c.search.includes("sort=score"))).toBe(true);
  });

  it("legacy runs keep reviewers A / B and do not offer the red-flag filter", async () => {
    setup();
    expect(await screen.findByRole("columnheader", { name: "Reviewers A / B" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Has red flags" })).not.toBeInTheDocument();
  });
});

describe("PapersPage · Simple and Detailed view", () => {
  beforeEach(() => localStorage.clear());

  it("starts in the Simple view: paper, group, criteria, why and library", async () => {
    setup({}, flat(`/?run=${RUN_ID}`));
    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["", "Paper", "Group", "Criteria", "Why", "Library"]);
    expect(within(table).getByText("Dropped: doesn't meet topic match (LLM).")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Simple" })).toHaveAttribute("aria-pressed", "true");
  });

  it("v switches to the Detailed view and the choice is remembered for this user", async () => {
    setup({}, flat(`/?run=${RUN_ID}`));
    await screen.findByRole("columnheader", { name: "Why" });
    await userEvent.keyboard("v");
    expect(await screen.findByRole("columnheader", { name: /Decision/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Detailed" })).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem("papers.view.11111111-1111-4111-8111-111111111111")).toBe("detailed");
    await userEvent.click(screen.getByRole("button", { name: "Simple" }));
    expect(await screen.findByRole("columnheader", { name: "Why" })).toBeInTheDocument();
  });

  it("lists v in the shortcuts sheet", async () => {
    setup({}, flat(`/?run=${RUN_ID}`));
    await screen.findByRole("table");
    await userEvent.keyboard("?");
    expect(within(screen.getByRole("dialog")).getByText("Switch between the Simple and Detailed view")).toBeInTheDocument();
  });
});

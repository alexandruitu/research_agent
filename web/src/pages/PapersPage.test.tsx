import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { lostRow, paperRow, runDetail, runOut, session, STAGES, RUN_ID } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { PapersPage } from "./PapersPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function Location() {
  const location = useLocation();
  return <output aria-label="location">{location.search}</output>;
}

const page = (items: unknown[], total = items.length, extra: Record<string, unknown> = {}) => ({ items, total, page: 1, page_size: 25, ...extra });

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
    { route },
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
    const strip = screen.getAllByRole("button", { name: /^(Search|Screen|Extract|Reviewers|Rank)/ });
    const status = (label: RegExp) => strip.find((b) => label.test(b.textContent ?? ""))!;
    expect(status(/Search/)).toHaveAttribute("data-status", "measured");
    expect(status(/Screen/)).toHaveAttribute("data-status", "measured");
    expect(status(/Reviewers/)).toHaveAttribute("data-status", "caveat");
    expect(status(/Reviewers/)).toHaveTextContent("one model family");
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
    const header = screen.getByRole("columnheader", { name: /Topic match/ });
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
    setup({ "GET /api/v1/runs/:id/papers": { body: page([], 0) } });
    expect(await screen.findByText("No papers match these filters.")).toBeInTheDocument();
  });

  it("shows the request id when the table cannot be loaded", async () => {
    setup({ "GET /api/v1/runs/:id/papers": { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "req-7" } } });
    expect(await screen.findByRole("alert")).toHaveTextContent("req-7");
  });

  it("asks for a run when there is none", async () => {
    setup({ "GET /api/v1/runs": { body: [] } });
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
  });
});

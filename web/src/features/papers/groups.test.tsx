import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../../api/client";
import { PapersPage } from "../../pages/PapersPage";
import { lostRow, paperRow, runDetail, runOut, session, STAGES, user } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  window.localStorage.clear();
});

function Location() {
  return <output aria-label="location">{useLocation().search}</output>;
}

const GROUPS = [
  { key: "read_first", label: "Read first", count: 1, rule: "Kept by screening, editor verdict include and 0 red flags." },
  { key: "worth_a_look", label: "Worth a look", count: 0, rule: "Kept, verdict include or uncertain and at most 1 red flag." },
  { key: "has_problems", label: "Has problems", count: 0, rule: "Kept, but 2 or more red flags or verdict exclude." },
  { key: "not_relevant", label: "Not relevant", count: 1, rule: "Dropped by screening." },
];
const page = (items: unknown[]) => ({ items, total: items.length, page: 1, page_size: 25 });

function setup(route = "/") {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session("member") },
    "GET /api/v1/runs": { body: [runOut()] },
    "GET /api/v1/runs/:id": { body: runDetail() },
    "GET /api/v1/stages": { body: STAGES },
    "GET /api/v1/runs/:id/papers/groups": ({ url }) => ({
      body: url.searchParams.get("by") === "year" ? [{ key: "2019", label: "2019", count: 1, rule: "Grouped by publication year." }] : GROUPS,
    }),
    "GET /api/v1/runs/:id/papers": ({ url }) => {
      const group = url.searchParams.get("group");
      return { body: page(group === "not_relevant" ? [lostRow()] : group === "read_first" || group === "2019" ? [paperRow()] : []) };
    },
  });
  renderWithProviders(<><Routes><Route path="/" element={<PapersPage />} /></Routes><Location /></>, { route });
  return api;
}

const head = (name: RegExp) => screen.findByRole("button", { name });

describe("quality groups", () => {
  it("shows each group with its count and rule; rows load per group, score first; Not relevant starts collapsed", async () => {
    const { calls } = setup();
    const readFirst = await head(/Read first 1 paper/);
    expect(readFirst).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Kept by screening, editor verdict include and 0 red flags.")).toBeInTheDocument();
    expect(await screen.findByText("Diagnostic accuracy of a deep learning approach to calculate FFR")).toBeInTheDocument();
    const request = calls.find((c) => c.search.includes("group=read_first"))!;
    expect(new URLSearchParams(request.search).get("sort")).toBe("score");
    expect(new URLSearchParams(request.search).get("direction")).toBe("desc");
    expect(new URLSearchParams(request.search).get("group_by")).toBe("quality");
    expect(await head(/Not relevant 1 paper/)).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Change in CT-Derived FFR/)).not.toBeInTheDocument();
    // empty groups are hidden, named on one line with a "why?" explanation
    expect(screen.queryByRole("button", { name: /Worth a look 0 papers/ })).not.toBeInTheDocument();
    const why = screen.getByRole("button", { name: /Worth a look — why\?/ });
    await userEvent.click(why);
    expect(screen.getByRole("tooltip")).toHaveTextContent("No kept paper has an include or uncertain verdict with at most 1 red flag.");
  });

  it("opens and closes a group from the keyboard and remembers it for this user", async () => {
    setup();
    const notRelevant = await head(/Not relevant/);
    notRelevant.focus();
    await userEvent.keyboard("{Enter}");
    expect(notRelevant).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText(/Change in CT-Derived FFR/)).toBeInTheDocument();
    await userEvent.click(await head(/Read first/));
    expect(JSON.parse(window.localStorage.getItem(`papers.collapsed.${user().id}.quality`)!)).toEqual(["read_first"]);
  });

  it("collapse all and expand all", async () => {
    setup();
    await head(/Read first/);
    await userEvent.click(screen.getByRole("button", { name: "Collapse all" }));
    for (const name of [/Read first/, /Worth a look/, /Has problems/, /Not relevant/]) expect(await head(name)).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(screen.getByRole("button", { name: "Expand all" }));
    expect(await head(/Not relevant/)).toHaveAttribute("aria-expanded", "true");
  });

  it("j and x work across groups; selecting rows in a group feeds the selection bar", async () => {
    setup();
    await userEvent.click(await head(/Not relevant/));
    await screen.findByText(/Change in CT-Derived FFR/);
    await userEvent.keyboard("j");
    await userEvent.keyboard("j");
    await userEvent.keyboard("x");
    expect(screen.getByRole("region", { name: "Selection" })).toHaveTextContent("1 selected");
    expect(screen.getByRole("checkbox", { name: /Select Change in CT-Derived/ })).toBeChecked();
  });

  it("group by is in the URL; None is the flat list with its pager", async () => {
    setup();
    await userEvent.selectOptions(await screen.findByLabelText("Group by"), "year");
    expect(screen.getByLabelText("location")).toHaveTextContent("group=year");
    expect(await head(/2019 1 paper/)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Group by"), "none");
    expect(await screen.findByText(/Page 1 of 1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Collapse all" })).not.toBeInTheDocument();
  });
});

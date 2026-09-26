import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { session, STAGES } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { SystemMapPage } from "./SystemMapPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const Location = () => <output aria-label="location">{useLocation().search}</output>;

function setup(route = "/system", stages: unknown = STAGES) {
  const api = mockApi({ "GET /api/v1/auth/me": { body: session("viewer") }, "GET /api/v1/stages": typeof stages === "object" && stages && "status" in (stages as object) ? (stages as never) : { body: stages } });
  renderWithProviders(<><Routes><Route path="/system" element={<SystemMapPage />} /></Routes><Location /></>, { route });
  return api;
}

describe("SystemMapPage", () => {
  it("shows every stage in pipeline order with its status in words", async () => {
    setup();
    const list = await screen.findByRole("list", { name: "Pipeline" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((li) => li.querySelector(".stage-title")?.textContent)).toEqual(STAGES.map((s) => s.title));
    const box = (title: string) => within(list).getByRole("button", { name: new RegExp(`^${title}`) });
    expect(box("Search")).toHaveAttribute("data-status", "measured");
    expect(box("Search")).toHaveTextContent("recall 15/16");
    expect(box("Reviewers A and B")).toHaveAttribute("data-status", "caveat");
    expect(box("Reviewers A and B")).toHaveTextContent("one model family");
    expect(box("Rank")).toHaveAttribute("data-status", "unmeasured");
    expect(box("Rank")).toHaveTextContent("not measured");
    expect(box("Topic")).toHaveAttribute("data-status", "input");
  });

  it("a stage opens its panel and the choice is in the URL", async () => {
    setup();
    await userEvent.click(await screen.findByRole("button", { name: /^Screen/ }));
    const panel = await screen.findByRole("complementary", { name: "About Screen" });
    expect(within(panel).getByText(/Jev decides when confident/)).toBeInTheDocument();
    expect(within(panel).getByText("Abstract only.")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "See the screened papers" })).toHaveAttribute("href", "/");
    expect(screen.getByLabelText("location")).toHaveTextContent("stage=screen");
  });

  it("opens straight to a stage from the URL and closes it again", async () => {
    setup("/system?stage=reviewers");
    const panel = await screen.findByRole("complementary", { name: "About Reviewers A and B" });
    expect(within(panel).getByRole("link", { name: "Open the eval report" })).toHaveAttribute("href", "/evals");
    await userEvent.click(within(panel).getByRole("button", { name: "Close stage details" }));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.getByLabelText("location")).not.toHaveTextContent("stage=");
  });

  it("ignores an unknown stage id in the URL", async () => {
    setup("/system?stage=nope");
    await screen.findByRole("list", { name: "Pipeline" });
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("says why when the catalog cannot be loaded", async () => {
    setup("/system", { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "req-3" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("req-3");
  });
});

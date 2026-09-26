import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../../api/client";
import { drawerOut, lostRow, paperRow, runDetail, runOut, session, STAGES, RUN_ID } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { PapersPage } from "../../pages/PapersPage";
import { StagePanel } from "./StagePanel";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const LOST_ID = "55555555-5555-4555-8555-555555555555";

function Location() {
  return <output aria-label="location">{useLocation().search}</output>;
}

/** The drawer is on screen (with a loading heading) before its data arrives: wait for the paper itself. */
async function openDrawer() {
  const drawer = await screen.findByRole("complementary", { name: "Paper details" });
  await within(drawer).findByRole("heading", { name: /Change in CT-Derived FFR/ });
  return drawer;
}

function setup(role: "viewer" | "member" = "member", extra: Parameters<typeof mockApi>[0] = {}, route = `/?run=${RUN_ID}&paper=${LOST_ID}`) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/runs": { body: [runOut()] },
    "GET /api/v1/runs/:id": { body: runDetail() },
    "GET /api/v1/stages": { body: STAGES },
    "GET /api/v1/runs/:id/papers": { body: { items: [paperRow(), lostRow()], total: 2, page: 1, page_size: 25 } },
    "GET /api/v1/runs/:id/papers/:id": { body: drawerOut() },
    ...extra,
  });
  renderWithProviders(<><Routes><Route path="/" element={<PapersPage />} /></Routes><Location /></>, { route });
  return api;
}

describe("paper drawer", () => {
  it("tells the story of the paper the screen lost, stage by stage", async () => {
    setup();
    const drawer = await openDrawer();
    expect(within(drawer).getByRole("heading", { name: /Change in CT-Derived FFR/ })).toHaveFocus();
    expect(within(drawer).getByText(/Found by direct lookup/)).toBeInTheDocument();
    expect(within(drawer).getByText("0.06")).toBeInTheDocument();
    expect(within(drawer).getByText("Jev was not confident, so the LLM decided.")).toBeInTheDocument();
    expect(within(drawer).getByText(/Auto-drop needs/)).toBeInTheDocument();
    expect(within(drawer).getByText(/70.8 and 67.4%/)).toBeInTheDocument();
    expect(within(drawer).getByText("Reviewer A")).toBeInTheDocument();
    expect(within(drawer).getByText("Adjudicator")).toBeInTheDocument();
    expect(within(drawer).getByText(/neither confirms nor rules out/)).toBeInTheDocument();
    expect(within(drawer).getByText(/Included by the systematic review/)).toBeInTheDocument();
  });

  it("shows the abstract on demand and never renders it as HTML", async () => {
    setup("viewer", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ paper: { ...drawerOut().paper, abstract: "<img src=x onerror=alert(1)> plain text" } }) } });
    await openDrawer();
    await userEvent.click(screen.getByRole("button", { name: "Abstract" }));
    expect(screen.getByText("<img src=x onerror=alert(1)> plain text")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("hides raw calls from viewers", async () => {
    setup("viewer");
    await openDrawer();
    expect(screen.queryByRole("button", { name: "Raw calls" })).not.toBeInTheDocument();
  });

  it("members can inspect the exact prompt and response of a call", async () => {
    const call = { key: "a".repeat(64), role: "screen", model: "anthropic:claude-sonnet-5", prompt_version: "m1.1", input: { payload: { topic: "t" } }, output: { decision: "exclude" } };
    const { calls } = setup("member", { [`GET /api/v1/runs/${RUN_ID}/calls/${"a".repeat(64)}`]: { body: call } });
    const drawer = await openDrawer();
    await userEvent.click(within(drawer).getByRole("button", { name: "Raw calls" }));
    await userEvent.click(within(drawer).getByRole("button", { name: /Screen/ }));
    expect(await screen.findByText("anthropic:claude-sonnet-5")).toBeInTheDocument();
    expect(screen.getByText(/"decision": "exclude"/)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith(`/calls/${"a".repeat(64)}`))).toBe(true);
  });

  it("explains an unavailable audit trail instead of failing silently", async () => {
    setup("member", { [`GET /api/v1/runs/${RUN_ID}/calls/${"a".repeat(64)}`]: { status: 409, body: { code: "no_audit_trail", message: "This run's audit trail is not available", request_id: "r" } } });
    const drawer = await openDrawer();
    await userEvent.click(within(drawer).getByRole("button", { name: "Raw calls" }));
    await userEvent.click(within(drawer).getByRole("button", { name: /Screen/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("audit trail is not available");
  });

  it("closes with Escape or the close button and returns focus to the paper's title", async () => {
    setup();
    await openDrawer();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Paper details" })).not.toBeInTheDocument());
    expect(screen.getByLabelText("location")).not.toHaveTextContent("paper=");
    await waitFor(() => expect(screen.getByRole("button", { name: /Change in CT-Derived FFR/ })).toHaveFocus());
    await userEvent.click(screen.getByRole("button", { name: /Change in CT-Derived FFR/ }));
    await openDrawer();
    await userEvent.click(screen.getByRole("button", { name: "Close paper details" }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Paper details" })).not.toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: /Change in CT-Derived FFR/ })).toHaveFocus());
  });

  it("ignores review detail keys it does not know, such as adjudicated", async () => {
    const base = drawerOut();
    const reviews = base.reviews.map((review) => ({ ...review, detail: { ...review.detail, adjudicated: true } }));
    setup("member", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ reviews }) } });
    const drawer = await openDrawer();
    expect(within(drawer).getByText(/neither confirms nor rules out/)).toBeInTheDocument();
    expect(within(drawer).queryByText(/true/)).not.toBeInTheDocument();
  });

  it("clicking a paper title opens its drawer and puts it in the URL", async () => {
    setup("member", {}, `/?run=${RUN_ID}`);
    await userEvent.click(await screen.findByRole("button", { name: /Change in CT-Derived FFR/ }));
    expect(await screen.findByRole("complementary", { name: "Paper details" })).toBeInTheDocument();
    expect(screen.getByLabelText("location")).toHaveTextContent(`paper=${LOST_ID}`);
  });

  it("shows a research-run paper without an SR section", async () => {
    setup("member", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ in_sr: null, label_source: null, found_by: "query" }) } });
    const drawer = await openDrawer();
    expect(within(drawer).queryByText(/systematic review/)).not.toBeInTheDocument();
    expect(within(drawer).getByText(/Found by the search query/)).toBeInTheDocument();
  });
});

describe("stage panel", () => {
  it("shows what a stage does, its status and its limits, and links to the eval data", () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("viewer") } });
    renderWithProviders(<StagePanel stage={STAGES.find((s) => s.id === "reviewers")!} onClose={() => undefined} />);
    expect(screen.getByRole("heading", { name: "Reviewers A and B" })).toBeInTheDocument();
    expect(screen.getByText("caveat: one model family")).toBeInTheDocument();
    expect(screen.getByText(/limits\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the eval report" })).toHaveAttribute("href", "/evals");
  });

  it("opens from a strip header and closes when the header is pressed again", async () => {
    setup("member", {}, `/?run=${RUN_ID}`);
    const strip = await screen.findByRole("button", { name: /^Screen/ });
    await userEvent.click(strip);
    expect(await screen.findByRole("complementary", { name: "About Screen" })).toBeInTheDocument();
    expect(screen.getByLabelText("location")).toHaveTextContent("stage=screen");
    await userEvent.click(screen.getByRole("button", { name: /^Screen/ }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "About Screen" })).not.toBeInTheDocument());
  });
});

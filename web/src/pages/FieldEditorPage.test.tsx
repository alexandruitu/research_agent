import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { evalSummary, fieldDetail, FIELD_ID, jobOut, testResult, legacyField, legacyVersion, RUN_ID, runOut, session, sourceRows, versionOut } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { FieldEditorPage } from "./FieldEditorPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(role: "viewer" | "member" | "admin" = "member", extra: Parameters<typeof mockApi>[0] = {}, route = `/fields/${FIELD_ID}`) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/fields/:id": { body: fieldDetail() },
    "GET /api/v1/sources": { body: sourceRows() },
    "GET /api/v1/runs": { body: [] },
    "GET /api/v1/evals": { body: [] },
    "GET /api/v1/fields/:id/versions/1": { body: legacyVersion() },
    "GET /api/v1/fields/:id/versions/2": { body: versionOut() },
    ...extra,
  });
  renderWithProviders(
    <Routes>
      <Route path="/fields/new" element={<FieldEditorPage />} />
      <Route path="/fields/:fieldId" element={<FieldEditorPage />} />
    </Routes>,
    { route },
  );
  return api;
}

const form = () => screen.findByRole("form", { name: "Field editor" });
/** Changing step moves focus to the step heading on the next frame; wait for it before typing. */
const settle = () => waitFor(() => expect(document.activeElement?.tagName).toBe("H2"));
const goStep = async (name: RegExp) => {
  await userEvent.click(within(screen.getByRole("navigation", { name: "Steps" })).getByRole("button", { name }));
  await settle();
};
const assistResult = () => ({
  mode: "demo", model: null,
  suggestions: {
    all: [{ term: "plaque", synonyms: ["atheroma"] }], any: [{ term: "deep learning", synonyms: [] }, { term: "CNN", synonyms: [] }], none: [{ term: "review", synonyms: [] }],
    include: ["The study is about plaque.", "The study reports results on patient images."], exclude: ["The paper is a review."],
  },
});
const previewResult = () => ({
  mode: "demo", years: { from: 2018, to: null },
  sources: [
    { source: "europepmc", query: "TITLE_ABS:plaque", effective_query: "TITLE_ABS:plaque AND PUB_YEAR:[2018 TO 3000]", count: 1234, papers: [{ id: "MED:1", title: "Plaque detection with CNNs", year: 2021 }], error: null },
    { source: "openalex", query: "plaque", effective_query: null, count: null, papers: [], error: "SourceUnavailable: openalex" },
  ],
});

describe("FieldEditorPage", () => {
  it("loads the current version into the form", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v2)" })).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Steps" })).getByRole("button", { name: /Keywords & criteria/ })).toHaveAttribute("aria-current", "step");
    expect(screen.getByLabelText("incl 1")).toHaveValue("The study uses machine learning or deep learning.");
    expect(screen.getByLabelText("excl 1")).toHaveValue("The paper is a review or an editorial.");
    expect(screen.getByLabelText("From year")).toHaveValue("2018");
    expect(screen.getByRole("button", { name: "Save as v3" })).toBeInTheDocument();
    await goStep(/Describe/);
    expect(screen.getByLabelText("Name")).toHaveValue("ML CT-FFR");
  });

  it("adds, reorders and removes criteria", async () => {
    setup();
    await form();
    await userEvent.click(screen.getByRole("button", { name: "Add inclusion criterion" }));
    await userEvent.type(screen.getByLabelText("incl 3"), "Results are compared with invasive FFR.");
    await userEvent.click(screen.getByRole("button", { name: "Move incl 3 up" }));
    expect(screen.getByLabelText("incl 2")).toHaveValue("Results are compared with invasive FFR.");
    expect(screen.getByRole("button", { name: "Move incl 1 up" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Remove incl 1" }));
    expect(screen.getByLabelText("incl 1")).toHaveValue("Results are compared with invasive FFR.");
    expect(screen.queryByLabelText("incl 3")).not.toBeInTheDocument();
  });

  it("validates before saving and does not call the server", async () => {
    const { calls } = setup();
    await form();
    await goStep(/Describe/);
    await userEvent.clear(screen.getByLabelText("Name"));
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Give the field a name.");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("saves the next version against the version it opened", async () => {
    const saved = fieldDetail({ current_version: 3, current: versionOut({ version: 3, note: "tightened" }) });
    const { calls } = setup("member", { "POST /api/v1/fields/:id/versions": { status: 201, body: saved } });
    await form();
    await userEvent.type(screen.getByLabelText("Change note"), "tightened");
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v3)" })).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ base_version: 2, note: "tightened", sources: ["europepmc"], years: { from: 2018, to: null } });
    expect((post.body as { include: unknown[] }).include).toHaveLength(2);
  });

  it("a stale save offers to reload the latest version", async () => {
    let loads = 0;
    setup("member", {
      "GET /api/v1/fields/:id": () => ({ body: ++loads === 1 ? fieldDetail() : fieldDetail({ current_version: 3, current: versionOut({ version: 3 }) }) }),
      "POST /api/v1/fields/:id/versions": { status: 409, body: { code: "stale_version", message: "This field changed since you opened it (now v3)", request_id: "r" } },
    });
    await form();
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    expect(await screen.findByText("This field changed since you opened it (now v3)")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reload the latest version" }));
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v3)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save as v4" })).toBeInTheDocument();
  });

  it("creates a new field and opens it", async () => {
    const created = fieldDetail({ current_version: 1, current: versionOut({ version: 1 }) });
    const { calls } = setup("member", { "POST /api/v1/fields": { status: 201, body: created }, "GET /api/v1/fields/:id": { body: created } }, "/fields/new");
    await form();
    expect(screen.getByRole("heading", { name: "New field" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name"), "ML CT-FFR");
    await userEvent.type(screen.getByLabelText("Description"), "Deep learning CT-FFR. Validated on patients.");
    await userEvent.click(screen.getByRole("button", { name: "Next →" }));
    await settle();
    await userEvent.type(screen.getByLabelText("Must include"), "CT-FFR{Enter}");
    await userEvent.click(screen.getByRole("button", { name: "Add inclusion criterion" }));
    await userEvent.type(screen.getByLabelText("incl 1"), "Uses deep learning.");
    await userEvent.click(screen.getByRole("button", { name: "Create field" }));
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v1)" })).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({
      name: "ML CT-FFR", topic: "Deep learning CT-FFR.", description: "Deep learning CT-FFR. Validated on patients.",
      keywords: { all: ["CT-FFR"], any: [], none: [] }, include: [{ text: "Uses deep learning." }], sources: ["europepmc"],
    });
    expect(screen.getByRole("button", { name: /Preview & save/ })).toHaveAttribute("aria-current", "step");
  });

  it("offers only enabled sources", async () => {
    setup();
    await form();
    expect(screen.getByRole("checkbox", { name: "Europe PMC" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "OpenAlex (disabled in Settings)" })).toBeDisabled();
  });

  it("is read-only for viewers", async () => {
    setup("viewer");
    await form();
    await goStep(/Describe/);
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Suggest keywords/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save as/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  });

  it("admins archive a field, which makes it read-only", async () => {
    const { calls } = setup("admin", { "POST /api/v1/fields/:id/archive": { body: fieldDetail({ archived_at: "2026-09-29T10:00:00Z" }) } });
    await form();
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(await screen.findByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.getByText(/This field is archived/)).toBeInTheDocument();
    expect(screen.getByLabelText("incl 1")).toBeDisabled();
    expect(calls.some((c) => c.method === "POST" && c.path.endsWith("/archive"))).toBe(true);
  });

  it("a legacy field explains how to add criteria", async () => {
    setup("member", { "GET /api/v1/fields/:id": { body: legacyField() } });
    expect(await screen.findByText(/legacy topic match/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save as v2" })).toBeInTheDocument();
  });

  it("the history lists versions with notes and runs, and says the screen is not measured", async () => {
    setup();
    const panel = await screen.findByRole("complementary", { name: "Field history" });
    expect(await within(panel).findByText(/not measured/)).toBeInTheDocument();
    expect(within(panel).getByText("added the exclusion")).toBeInTheDocument();
    expect(within(panel).getByText(/3 runs/)).toBeInTheDocument();
    expect(await within(panel).findByText("The study uses machine learning or deep learning.")).toBeInTheDocument();
    expect(within(panel).getAllByText("added").length).toBeGreaterThan(0);
    expect(within(panel).getAllByText("removed").length).toBeGreaterThan(0);
  });

  it("says the screen is measured when an eval ran on this version", async () => {
    setup("member", {
      "GET /api/v1/runs": { body: [runOut({ id: RUN_ID, field_id: FIELD_ID, field_version: 2 })] },
      "GET /api/v1/evals": { body: [evalSummary()] },
    });
    const panel = await screen.findByRole("complementary", { name: "Field history" });
    await waitFor(() => expect(panel).toHaveTextContent("measured against mlffrct-2024"));
  });

  it("tests the unsaved edits in demo mode and shows the results", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/fields/:id/test": { status: 202, body: jobOut({ kind: "criteria_test", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "criteria_test", run_id: null, status: "done", progress: { status: "done", result: testResult() } }) },
    });
    await form();
    await userEvent.clear(screen.getByLabelText("excl 1"));
    await userEvent.type(screen.getByLabelText("excl 1"), "The paper is a review.");
    await userEvent.click(screen.getByRole("checkbox", { name: /Demo mode/ }));
    await goStep(/Preview & save/);
    await userEvent.click(screen.getByRole("button", { name: "Test criteria" }));
    expect(await screen.findByRole("region", { name: "Criteria test" })).toBeInTheDocument();
    expect(await screen.findByRole("table")).toBeInTheDocument();
    const post = calls.find((c) => c.method === "POST")!;
    expect(post.body).toMatchObject({ mode: "demo", draft: { exclude: [{ text: "The paper is a review." }] } });
    expect((post.body as { draft: Record<string, unknown> }).draft).not.toHaveProperty("note");
  });

  it("shows why the server refused a test", async () => {
    setup("member", { "POST /api/v1/fields/:id/test": { status: 422, body: { code: "no_enabled_source", message: "None of this field's sources is enabled", request_id: "r" } } });
    await form();
    await goStep(/Preview & save/);
    await userEvent.click(screen.getByRole("button", { name: "Test criteria" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("None of this field's sources is enabled");
  });

  it("suggests keywords and criteria from the description; nothing is applied until accepted", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/fields/assist": { status: 202, body: jobOut({ kind: "field_assist", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "field_assist", run_id: null, status: "done", progress: { status: "done", result: assistResult() } }) },
    }, "/fields/new");
    await form();
    await userEvent.type(screen.getByLabelText("Description"), "AI for coronary plaque on CT");
    await userEvent.click(screen.getByRole("checkbox", { name: /Demo mode/ }));
    await userEvent.click(screen.getByRole("button", { name: "Suggest keywords & criteria" }));
    const panel = await screen.findByRole("region", { name: /Suggestions/ });
    expect(calls.find((c) => c.path.endsWith("/assist"))?.body).toEqual({ description: "AI for coronary plaque on CT", topic: "", keywords: null, mode: "demo" });
    const summary = screen.getByRole("complementary", { name: "Field summary" });
    expect(summary).toHaveTextContent(/Must include\s*–/);
    await userEvent.click(within(panel).getByRole("button", { name: /plaque \(Must include\)/ }));
    expect(within(panel).getByRole("button", { name: /plaque \(Must include\)/ })).toHaveAttribute("aria-pressed", "true");
    expect(summary).toHaveTextContent(/Must include\s*plaque/);
    expect(summary).not.toHaveTextContent("CNN");
    await userEvent.click(within(panel).getByRole("button", { name: /atheroma/ }));
    await userEvent.click(within(panel).getByRole("button", { name: "Accept all" }));
    await goStep(/Keywords & criteria/);
    expect(within(screen.getByRole("list", { name: "At least one of keywords" })).getByText("atheroma")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "Exclude keywords" })).getByText("review")).toBeInTheDocument();
    expect(screen.getByLabelText("incl 2")).toHaveValue("The study reports results on patient images.");
    expect(screen.getByLabelText("excl 1")).toHaveValue("The paper is a review.");
  });

  it("says what to do when there is nothing to suggest from", async () => {
    setup("member", { "POST /api/v1/fields/assist": { status: 422, body: { code: "nothing_to_assist", message: "Describe the field or add a keyword first", request_id: "r" } } }, "/fields/new");
    await form();
    await userEvent.click(screen.getByRole("button", { name: "Suggest keywords & criteria" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Describe the field or add a keyword first");
  });

  it("builds the query per source live, and an override replaces it", async () => {
    setup();
    await form();
    await userEvent.type(screen.getByLabelText("Must include"), "plaque{Enter}");
    await userEvent.type(screen.getByLabelText("At least one of"), "deep learning, CNN,");
    expect(screen.getByRole("status", { name: "Query for Europe PMC" })).toHaveTextContent('TITLE_ABS:plaque AND (TITLE_ABS:"deep learning" OR TITLE_ABS:CNN)');
    await userEvent.click(screen.getByRole("button", { name: "Remove CNN from At least one of" }));
    expect(screen.getByRole("status", { name: "Query for Europe PMC" })).toHaveTextContent('TITLE_ABS:plaque AND TITLE_ABS:"deep learning"');
    await userEvent.click(screen.getByText(/Advanced: override query/));
    await userEvent.type(screen.getByLabelText("Override for Europe PMC"), "my own query");
    expect(screen.getByRole("status", { name: "Query for Europe PMC" })).toHaveTextContent("my own query");
    expect(screen.getByText("your override")).toBeInTheDocument();
  });

  it("Backspace in an empty keyword box removes the last keyword", async () => {
    setup();
    await form();
    const input = screen.getByLabelText("Exclude");
    await userEvent.type(input, "review{Enter}editorial{Enter}");
    await userEvent.type(input, "{Backspace}");
    const group = screen.getByRole("list", { name: "Exclude keywords" });
    expect(within(group).getByText("review")).toBeInTheDocument();
    expect(within(group).queryByText("editorial")).not.toBeInTheDocument();
  });

  it("previews the search per source: counts, titles and a failing source", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/fields/preview": { status: 202, body: jobOut({ kind: "field_preview", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "field_preview", run_id: null, status: "done", progress: { status: "done", result: previewResult() } }) },
    });
    await form();
    await userEvent.type(screen.getByLabelText("Must include"), "plaque{Enter}");
    await goStep(/Preview & save/);
    await userEvent.click(screen.getByRole("button", { name: "Preview search" }));
    const panel = await screen.findByRole("region", { name: "Search preview" });
    expect(await within(panel).findByText("1,234 papers")).toBeInTheDocument();
    expect(within(panel).getByText("Plaque detection with CNNs")).toBeInTheDocument();
    expect(within(panel).getByText("SourceUnavailable: openalex")).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/preview"))?.body).toEqual({
      keywords: { all: ["plaque"], any: [], none: [] }, query_override: null, sources: ["europepmc"], years: { from: 2018, to: null }, mode: "live",
    });
  });

  it("explains the preview rate limit", async () => {
    setup("member", { "POST /api/v1/fields/preview": { status: 429, body: { code: "rate_limited", message: "Too many previews; try again in a minute", request_id: "r" } } });
    await form();
    await userEvent.type(screen.getByLabelText("Must include"), "plaque{Enter}");
    await goStep(/Preview & save/);
    await userEvent.click(screen.getByRole("button", { name: "Preview search" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many previews in a minute");
  });

  it("the step survives a reload through the URL", async () => {
    setup("member", {}, `/fields/${FIELD_ID}?step=3`);
    expect(await screen.findByRole("heading", { name: /3 · Preview & save/ })).toBeInTheDocument();
  });
});

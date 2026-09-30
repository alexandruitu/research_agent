import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { ModelsTab } from "../features/settings/ModelsTab";
import { FulltextTab } from "../features/settings/FulltextTab";
import { ScreeningTab } from "../features/settings/ScreeningTab";
import { SourcesTab } from "../features/settings/SourcesTab";
import { evalSummary, JOB_ID, jobOut, modelsAvailable, reviewerRows, reviewSettings, session, settingsContent, sourceRows, workerRows } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { SettingsPage } from "./SettingsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(role: "viewer" | "member" | "admin", route: string, extra: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/sources": { body: sourceRows() },
    "GET /api/v1/settings": { body: { contact_email: "lab@example.org" } },
    "GET /api/v1/workers/status": { body: workerRows() },
    "GET /api/v1/settings/review": { body: reviewSettings() },
    "GET /api/v1/reviewers": { body: reviewerRows() },
    "GET /api/v1/models/available": { body: modelsAvailable() },
    "GET /api/v1/evals": { body: [evalSummary()] },
    ...extra,
  });
  renderWithProviders(
    <Routes>
      <Route path="/settings" element={<SettingsPage />}>
        <Route path="sources" element={<SourcesTab />} />
        <Route path="models" element={<ModelsTab />} />
        <Route path="screening" element={<ScreeningTab />} />
        <Route path="fulltext" element={<FulltextTab />} />
      </Route>
    </Routes>,
    { route },
  );
  return api;
}

describe("Settings tabs", () => {
  it("lists the tabs in order, Users for admins only", async () => {
    setup("admin", "/settings/sources");
    const nav = await screen.findByRole("navigation", { name: "Settings sections" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual(["Sources", "Reviewers", "AI models", "Screening", "Full text", "Users"]);
  });

  it("explains read-only mode to non-admins", async () => {
    setup("viewer", "/settings/sources");
    expect(await screen.findByText(/Every run records the settings version it used/)).toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Settings sections" })).queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });
});

describe("Settings → Sources", () => {
  it("lists every source with its status and last check in words", async () => {
    setup("admin", "/settings/sources");
    await screen.findByRole("heading", { name: "Biomedical" });
    const rows = screen.getAllByRole("row");
    const row = (name: RegExp) => rows.find((r) => within(r).queryByRole("rowheader", { name }))!;
    expect(row(/Europe PMC/)).toHaveTextContent("✓ OK · 0.8 s");
    expect(row(/OpenAlex/)).toHaveTextContent("never checked");
    expect(row(/arXiv/)).toHaveTextContent("✗ failed: SourceUnavailable: arxiv");
  });

  it("groups sources with an intro each, says what keys they need, and explains Google Scholar", async () => {
    setup("viewer", "/settings/sources");
    const headings = (await screen.findAllByRole("heading", { level: 3 })).map((h) => h.textContent);
    expect(headings).toEqual(["Biomedical", "Preprints", "Multidisciplinary", "Publishers (licensed)", "Identity"]);
    const publishers = screen.getByRole("table", { name: "Publishers (licensed)" });
    expect(within(publishers).getByRole("row", { name: /IEEE Xplore/ })).toHaveTextContent("Key required: set IEEE_API_KEYKey not set in the worker");
    const multi = screen.getByRole("table", { name: "Multidisciplinary" });
    expect(within(multi).getByRole("row", { name: /CORE/ })).toHaveTextContent("Key set · accepted");
    expect(within(multi).getByRole("row", { name: /OpenAlex/ })).toHaveTextContent("Optional key: set OPENALEX_API_KEY for higher limits");
    expect(screen.getByRole("table", { name: "Biomedical" })).toHaveTextContent("No key needed");
    expect(screen.getByRole("complementary", { name: "Google Scholar" })).toHaveTextContent("no official API");
  });

  it("a source whose required key is missing cannot be enabled, and says why", async () => {
    setup("admin", "/settings/sources");
    const toggle = await screen.findByRole("switch", { name: /IEEE Xplore/ });
    expect(toggle).toBeDisabled();
    expect(toggle).toHaveAccessibleDescription("Set IEEE_API_KEY in the worker environment first, then restart the worker.");
    expect(screen.getByRole("switch", { name: /CORE/ })).toBeEnabled();
    expect(screen.queryByRole("switch", { name: /Unpaywall/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test Unpaywall" })).not.toBeInTheDocument();
  });

  it("admins enable a source", async () => {
    const openalex = sourceRows().find((s) => s.name === "openalex")!;
    const { calls } = setup("admin", "/settings/sources", { "PATCH /api/v1/sources/openalex": { body: { ...openalex, enabled: true } } });
    await userEvent.click(await screen.findByRole("switch", { name: /OpenAlex/ }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ enabled: true }));
  });

  it("admins change max results, and a value outside 1 to 200 is refused before calling the server", async () => {
    const { calls } = setup("admin", "/settings/sources", { "PATCH /api/v1/sources/europepmc": { body: { ...sourceRows()[0], max_results: 50 } } });
    const input = await screen.findByLabelText("Max results per run for Europe PMC");
    await userEvent.clear(input);
    await userEvent.type(input, "500");
    await userEvent.click(screen.getByRole("button", { name: "Save max results for Europe PMC" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("1 to 200");
    expect(calls.some((c) => c.method === "PATCH")).toBe(false);
    await userEvent.clear(input);
    await userEvent.type(input, "50");
    await userEvent.click(screen.getByRole("button", { name: "Save max results for Europe PMC" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ max_results: 50 }));
  });

  it("Test runs a check job and shows its result", async () => {
    const { calls } = setup("admin", "/settings/sources", {
      "POST /api/v1/sources/openalex/check": { status: 202, body: jobOut({ kind: "source_check", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "source_check", status: "done", run_id: null, progress: { status: "done", result: { ok: true, ms: 1200, count: 1, error: null } } }) },
    });

    await userEvent.click(await screen.findByRole("button", { name: "Test OpenAlex" }));
    expect(await screen.findByText(/✓ OK · 1.2 s/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === `/api/v1/jobs/${JOB_ID}`)).toBe(true);
  });

  it("saves the contact address, and an empty address clears it", async () => {
    const { calls } = setup("admin", "/settings/sources", { "PATCH /api/v1/settings": ({ body }) => ({ body }) });
    const input = await screen.findByLabelText("Contact address for public APIs");
    await userEvent.clear(input);
    await userEvent.click(screen.getByRole("button", { name: "Save contact address" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ contact_email: null }));
  });

  it("is read-only for members and viewers", async () => {
    setup("member", "/settings/sources");
    await screen.findByRole("table", { name: "Biomedical" });
    expect(screen.getByText(/Read-only/)).toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Test/ })).not.toBeInTheDocument();
    expect(screen.getByText(/lab@example.org/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });
});

describe("Settings → AI models", () => {
  it("shows each role's model and whether its key was accepted, in words", async () => {
    setup("viewer", "/settings/models");
    const table = within(await screen.findByRole("region", { name: "Keys reported by the worker" })).getByRole("table");
    expect(within(table).getByRole("row", { name: /Screen/ })).toHaveTextContent("✓ accepted");
    expect(within(table).getByRole("row", { name: /Adjudicator/ })).toHaveTextContent("✗ rejected: rejected (401)");
    expect(within(table).getByRole("row", { name: /Jev/ })).toHaveTextContent("✗ missing");
    expect(screen.getByText(/Key values never leave the worker/)).toBeInTheDocument();
  });

  it("says so when no worker has reported", async () => {
    setup("admin", "/settings/models", { "GET /api/v1/workers/status": { body: [] } });
    expect(await screen.findByText(/No worker has reported yet/)).toBeInTheDocument();
  });
});

const savedEcho = ({ body }: { body: unknown }) => {
  const b = body as ReturnType<typeof settingsContent> & { note: string; base_version: number };
  return { status: 201, body: reviewSettings({ ...b }, b.base_version + 1) };
};
const posted = (calls: { method: string; path: string; body: unknown }[]) => calls.find((c) => c.method === "POST" && c.path === "/api/v1/settings/review")?.body as Record<string, unknown> | undefined;

describe("Settings → Screening", () => {
  it("explains the bands in words and saves the four thresholds as the next version with a note", async () => {
    const { calls } = setup("admin", "/settings/screening", { "POST /api/v1/settings/review": savedEcho });
    expect(await screen.findByText("Used by next run · v3")).toBeInTheDocument();
    expect(screen.getByText(/≤ 0.05: dropped by Jev · between: the LLM decides · ≥ 0.80: kept by Jev/)).toBeInTheDocument();
    const keep = screen.getByLabelText("Keep from");
    await userEvent.clear(keep);
    await userEvent.type(keep, "0.9");
    expect(screen.getByText(/≥ 0.90: kept by Jev/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Change note"), "stricter keep");
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    await waitFor(() => expect(posted(calls)).toMatchObject({ screening: { ...settingsContent().screening, keep_min: 0.9 }, note: "stricter keep", base_version: 3, default_panel: settingsContent().default_panel }));
    expect(await screen.findByText(/Saved as v4/)).toBeInTheDocument();
  });

  it("refuses inverted bands before calling the server", async () => {
    const { calls } = setup("admin", "/settings/screening");
    const drop = await screen.findByLabelText("Drop at or below");
    await userEvent.clear(drop);
    await userEvent.type(drop, "0.95");
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must be lower than “Keep from”");
    expect(posted(calls)).toBeUndefined();
  });

  it("maps the Evals recommendation exactly for inclusion criteria and applies it", async () => {
    setup("admin", "/settings/screening");
    const hint = await screen.findByRole("complementary", { name: "Evals recommendation" });
    expect(hint).toHaveTextContent("keep from 0.55, drop at or below 0.15");
    expect(hint).toHaveTextContent(/Exclusion criteria have no measured recommendation/);
    await userEvent.click(within(hint).getByRole("button", { name: "Apply to inclusion criteria" }));
    expect(screen.getByLabelText("Keep from")).toHaveValue(0.55);
    expect(screen.getByLabelText("Drop at or below")).toHaveValue(0.15);
    expect(screen.getByLabelText("Drop from")).toHaveValue(0.95);
  });

  it("shows a stale save with a reload button", async () => {
    setup("admin", "/settings/screening", { "POST /api/v1/settings/review": { status: 409, body: { code: "stale_version", message: "The settings changed since you opened them (now v4)", request_id: "r" } } });
    const keep = await screen.findByLabelText("Keep from");
    await userEvent.clear(keep);
    await userEvent.type(keep, "0.9");
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    expect(await screen.findByText(/changed since you opened them/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload the latest version" })).toBeInTheDocument();
  });

  it("asks before leaving the tab with unsaved changes", async () => {
    setup("admin", "/settings/screening");
    const keep = await screen.findByLabelText("Keep from");
    await userEvent.clear(keep);
    await userEvent.type(keep, "0.9");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await userEvent.click(screen.getByRole("link", { name: "Sources" }));
    expect(confirm).toHaveBeenCalled();
    expect(screen.getByLabelText("Keep from")).toBeInTheDocument();
    confirm.mockRestore();
  });

  it("Reset to default puts the shipped thresholds back", async () => {
    setup("admin", "/settings/screening", { "GET /api/v1/settings/review": { body: reviewSettings({ screening: { keep_min: 0.7, include_fail_max: 0.1, exclude_hit_min: 0.9, exclude_clear_max: 0.3 } }) } });
    await userEvent.click(await screen.findByRole("button", { name: "Reset to default" }));
    expect(screen.getByLabelText("Keep from")).toHaveValue(0.8);
  });

  it("is read-only for viewers", async () => {
    setup("viewer", "/settings/screening");
    expect(await screen.findByLabelText("Keep from")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Apply to inclusion criteria" })).not.toBeInTheDocument();
  });
});

describe("Settings → Full text", () => {
  it("turns a source off and saves the full-text settings", async () => {
    const { calls } = setup("admin", "/settings/fulltext", { "POST /api/v1/settings/review": savedEcho });
    const upload = await screen.findByRole("switch", { name: /PDFs uploaded by your team/ });
    expect(upload).toHaveAccessibleDescription(/Members can upload a PDF/);
    await userEvent.click(upload);
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    await waitFor(() => expect(posted(calls)?.fulltext).toEqual({ sources: ["pmc_oa", "unpaywall"], contact: "lab@example.org", max_chars: 60000, upload_max_mb: 30 }));
  });

  it("orders the resolvers with up/down buttons and explains each licence", async () => {
    const { calls } = setup("admin", "/settings/fulltext", { "POST /api/v1/settings/review": savedEcho });
    const up = await screen.findByRole("button", { name: "Move PDFs uploaded by your team up" });
    expect(screen.getByRole("button", { name: "Move PubMed Central Open Access up" })).toBeDisabled();
    await userEvent.click(up);
    const core = screen.getByRole("switch", { name: /^CORE/ });
    expect(core).toHaveAccessibleDescription(/Needs CORE_API_KEY in the worker\. Licence: Open-access copies only/);
    expect(core).toHaveAccessibleDescription(/Key set · accepted/);
    await userEvent.click(core);
    expect(screen.getByRole("switch", { name: /ScienceDirect/ })).toHaveAccessibleDescription(/never exported/);
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    await waitFor(() => expect((posted(calls)?.fulltext as { sources?: string[] } | undefined)?.sources).toEqual(["pmc_oa", "upload", "unpaywall", "core"]));
  });

  it("needs a contact email while Unpaywall is on, and limits the upload size", async () => {
    const { calls } = setup("admin", "/settings/fulltext");
    await userEvent.clear(await screen.findByLabelText(/Contact email for Unpaywall/));
    const limit = screen.getByLabelText(/Upload limit/);
    await userEvent.clear(limit);
    await userEvent.type(limit, "40");
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Unpaywall needs a contact email.");
    expect(alert).toHaveTextContent("1 to 30 MB");
    expect(posted(calls)).toBeUndefined();
  });

  it("shows the server's message when the pipeline refuses the settings", async () => {
    setup("admin", "/settings/fulltext", { "POST /api/v1/settings/review": { status: 422, body: { code: "invalid_settings", message: "fulltext: contact is required for unpaywall", request_id: "r" } } });
    await userEvent.click(await screen.findByRole("switch", { name: /PubMed Central/ }));
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("contact is required for unpaywall");
  });

  it("is read-only for members", async () => {
    setup("member", "/settings/fulltext");
    expect(await screen.findByRole("switch", { name: /Unpaywall/ })).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument();
  });
});

describe("Settings → AI models (choices)", () => {
  it("has one row per role, each panel reviewer and the editor, limited to available models", async () => {
    setup("admin", "/settings/models");
    const table = await screen.findByRole("table", { name: "Model per role" });
    for (const role of ["Plan", "Screen", "Extract", "Methodologist", "Clinician", "Statistician", "Editor"]) {
      expect(within(table).getByRole("combobox", { name: `Model for ${role}` })).toBeInTheDocument();
    }
    const stat = within(table).getByRole("combobox", { name: "Model for Statistician" });
    expect(stat).toHaveValue("openai:gpt-6");
    expect(within(stat).getByRole("option", { name: "openai:gpt-6 (key not accepted)" })).toBeInTheDocument();
    expect(screen.queryByText(/All reviewers use one model family/)).not.toBeInTheDocument();
  });

  it("warns in words when every reviewer uses one family, and saving creates a reviewer version", async () => {
    const { calls } = setup("admin", "/settings/models", { "POST /api/v1/reviewers/statistician/versions": { status: 201, body: reviewerRows()[2] } });
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Model for Statistician" }), "anthropic:claude-sonnet-5");
    expect(screen.getByRole("note")).toHaveTextContent("All reviewers use one model family (anthropic)");
    expect(screen.getByText(/also creates a new version of Statistician/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/v1/reviewers/statistician/versions")?.body).toMatchObject({ model: "anthropic:claude-sonnet-5", base_version: 2, name: "Statistician" }));
    expect(posted(calls)).toBeUndefined();
  });

  it("saves pipeline and editor models as a settings version", async () => {
    const { calls } = setup("admin", "/settings/models", { "POST /api/v1/settings/review": savedEcho });
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Model for Extract" }), "anthropic:claude-opus-5-5");
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Model for Editor" }), "");
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    await waitFor(() => expect(posted(calls)).toMatchObject({ models: { extract: "anthropic:claude-opus-5-5" }, editor: { model: null, instructions: settingsContent().editor.instructions } }));
  });

  it("is read-only for viewers", async () => {
    setup("viewer", "/settings/models");
    expect(await screen.findByRole("combobox", { name: "Model for Plan" })).toBeDisabled();
  });
});

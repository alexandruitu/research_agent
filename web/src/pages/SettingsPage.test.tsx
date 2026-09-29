import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { ModelsTab } from "../features/settings/ModelsTab";
import { SourcesTab } from "../features/settings/SourcesTab";
import { JOB_ID, jobOut, session, sourceRows, workerRows } from "../test/fixtures";
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
    ...extra,
  });
  renderWithProviders(
    <Routes>
      <Route path="/settings" element={<SettingsPage />}>
        <Route path="sources" element={<SourcesTab />} />
        <Route path="models" element={<ModelsTab />} />
      </Route>
    </Routes>,
    { route },
  );
  return api;
}

describe("Settings → Sources", () => {
  it("lists every source with its status and last check in words", async () => {
    setup("admin", "/settings/sources");
    const table = await screen.findByRole("table");
    const europe = within(table).getByRole("row", { name: /Europe PMC/ });
    expect(europe).toHaveTextContent("✓ OK · 0.8 s");
    expect(within(table).getByRole("row", { name: /OpenAlex/ })).toHaveTextContent("never checked");
    expect(within(table).getByRole("row", { name: /arXiv/ })).toHaveTextContent("✗ failed: SourceUnavailable: arxiv");
  });

  it("admins enable a source", async () => {
    const { calls } = setup("admin", "/settings/sources", { "PATCH /api/v1/sources/openalex": { body: { ...sourceRows()[1], enabled: true } } });
    await userEvent.click(await screen.findByRole("checkbox", { name: /OpenAlex/ }));
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
    await screen.findByRole("table");
    expect(screen.getByText(/Read-only/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Test/ })).not.toBeInTheDocument();
    expect(screen.getByText(/lab@example.org/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });
});

describe("Settings → AI models", () => {
  it("shows each role's model and whether its key was accepted, in words", async () => {
    setup("viewer", "/settings/models");
    const table = await screen.findByRole("table");
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

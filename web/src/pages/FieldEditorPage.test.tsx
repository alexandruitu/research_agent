import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { evalSummary, fieldDetail, FIELD_ID, legacyField, legacyVersion, RUN_ID, runOut, session, sourceRows, versionOut } from "../test/fixtures";
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

describe("FieldEditorPage", () => {
  it("loads the current version into the form", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v2)" })).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("ML CT-FFR");
    expect(screen.getByLabelText("incl 1")).toHaveValue("The study uses machine learning or deep learning.");
    expect(screen.getByLabelText("excl 1")).toHaveValue("The paper is a review or an editorial.");
    expect(screen.getByLabelText("From year")).toHaveValue("2018");
    expect(screen.getByRole("button", { name: "Save as v3" })).toBeInTheDocument();
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
    expect(await screen.findByRole("heading", { name: "New field" })).toBeInTheDocument();
    expect(screen.getByText(/Save the field first/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Name"), "ML CT-FFR");
    await userEvent.type(screen.getByLabelText(/^Topic/), "deep learning CT-FFR");
    await userEvent.click(screen.getByRole("button", { name: "Add inclusion criterion" }));
    await userEvent.type(screen.getByLabelText("incl 1"), "Uses deep learning.");
    await userEvent.click(screen.getByRole("button", { name: "Create field" }));
    expect(await screen.findByRole("heading", { name: "ML CT-FFR (v1)" })).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ name: "ML CT-FFR", include: [{ text: "Uses deep learning." }], sources: ["europepmc"] });
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
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Save as/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
  });

  it("admins archive a field, which makes it read-only", async () => {
    const { calls } = setup("admin", { "POST /api/v1/fields/:id/archive": { body: fieldDetail({ archived_at: "2026-09-29T10:00:00Z" }) } });
    await form();
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(await screen.findByRole("button", { name: "Restore" })).toBeInTheDocument();
    expect(screen.getByText(/This field is archived/)).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeDisabled();
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
});

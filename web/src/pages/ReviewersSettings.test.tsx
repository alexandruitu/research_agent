import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { ReviewerEditorPage } from "../features/settings/ReviewerEditor";
import { ReviewersTab } from "../features/settings/ReviewersTab";
import { modelsAvailable, reviewerOut, reviewerRows, reviewSettings, session } from "../test/fixtures";
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
    "GET /api/v1/settings/review": { body: reviewSettings() },
    "GET /api/v1/reviewers": ({ url }) => ({ body: url.searchParams.get("archived") === "true" ? [...reviewerRows(), reviewerOut("radiologist", "Radiologist", { archived_at: "2026-09-20T00:00:00Z", in_default_panel: false })] : reviewerRows() }),
    "GET /api/v1/reviewers/methodologist": { body: reviewerOut() },
    "GET /api/v1/models/available": { body: modelsAvailable() },
    ...extra,
  });
  renderWithProviders(
    <Routes>
      <Route path="/settings" element={<SettingsPage />}>
        <Route path="reviewers" element={<ReviewersTab />} />
        <Route path="reviewers/new" element={<ReviewerEditorPage />} />
        <Route path="reviewers/:reviewerKey" element={<ReviewerEditorPage />} />
      </Route>
    </Routes>,
    { route },
  );
  return api;
}

const settingsPost = (calls: { method: string; path: string; body: unknown }[]) => calls.find((c) => c.method === "POST" && c.path === "/api/v1/settings/review")?.body as Record<string, unknown> | undefined;

describe("Settings → Reviewers", () => {
  it("shows a card per reviewer: role, item count, red flags, model and panel switch", async () => {
    setup("admin", "/settings/reviewers");
    const cards = await screen.findAllByRole("listitem");
    const first = cards[0]!;
    expect(within(first).getByRole("link", { name: "Methodologist" })).toHaveAttribute("href", "/settings/reviewers/methodologist");
    expect(first).toHaveTextContent("You judge the study as a methodologist.");
    expect(first).toHaveTextContent("2 items · 1 can raise a red flag");
    expect(first).toHaveTextContent("anthropic:claude-sonnet-5");
    expect(within(first).getByRole("switch", { name: /In the default panel/ })).toBeChecked();
    expect(screen.getByText(/Default panel: 3 of 5 reviewers/)).toBeInTheDocument();
  });

  it("changes the default panel and the editor instructions in one settings version", async () => {
    const { calls } = setup("admin", "/settings/reviewers", { "POST /api/v1/settings/review": { status: 201, body: reviewSettings({ default_panel: ["methodologist", "statistician"] }, 4) } });
    await userEvent.click(await screen.findByRole("switch", { name: /In the default panel \(Clinician\)/ }));
    const instructions = screen.getByLabelText("Editor instructions");
    await userEvent.clear(instructions);
    await userEvent.type(instructions, "Be strict about leakage.");
    await userEvent.click(screen.getByRole("button", { name: "Save as v4" }));
    await waitFor(() => expect(settingsPost(calls)).toMatchObject({ default_panel: ["methodologist", "statistician"], editor: { instructions: "Be strict about leakage." }, base_version: 3 }));
  });

  it("keeps at least one reviewer in the panel and explains why", async () => {
    setup("admin", "/settings/reviewers", { "GET /api/v1/settings/review": { body: reviewSettings({ default_panel: ["methodologist"] }) } });
    const only = await screen.findByRole("switch", { name: /\(Methodologist\)/ });
    expect(only).toBeDisabled();
    expect(only).toHaveAccessibleDescription("The panel needs at least one reviewer.");
  });

  it("lists archived reviewers on request with Restore", async () => {
    const { calls } = setup("admin", "/settings/reviewers", { "POST /api/v1/reviewers/radiologist/restore": { body: reviewerOut("radiologist", "Radiologist") } });
    await userEvent.click(await screen.findByRole("button", { name: "Show archived reviewers" }));
    await userEvent.click(await screen.findByRole("button", { name: "Restore Radiologist" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/reviewers/radiologist/restore")).toBe(true));
  });

  it("is read-only for members", async () => {
    setup("member", "/settings/reviewers");
    expect(await screen.findByRole("switch", { name: /\(Methodologist\)/ })).toBeDisabled();
    expect(screen.queryByRole("link", { name: "New reviewer" })).not.toBeInTheDocument();
  });
});

describe("Reviewer editor", () => {
  it("previews only item keys and text, and says weights and red flags are hidden from the model", async () => {
    setup("admin", "/settings/reviewers/methodologist");
    const previewBox = await screen.findByRole("complementary", { name: "What the model reads" });
    expect(previewBox).toHaveTextContent("m1 Data were split at patient level, not image level.");
    expect(previewBox).toHaveTextContent(/Not shown to the model: weights, what a good answer is and red-flag rules/);
    await userEvent.type(screen.getByLabelText("Question for item 2 text"), " Also prospectively.");
    expect(previewBox).toHaveTextContent("external dataset. Also prospectively.");
  });

  it("adds an item with weight, red-flag rule and source, and saves the next version", async () => {
    const { calls } = setup("admin", "/settings/reviewers/methodologist", {
      "POST /api/v1/reviewers/methodologist/versions": { status: 201, body: reviewerOut("methodologist", "Methodologist", { current_version: 3 }) },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Add item" }));
    await userEvent.type(screen.getByLabelText("Question for item 3 text"), "The reference standard is described.");
    const weights = screen.getByRole("group", { name: "Weight of item 3" });
    await userEvent.click(within(weights).getByRole("radio", { name: /3 · high/ }));
    await userEvent.selectOptions(screen.getByLabelText("Red flag rule for item 3"), "no");
    await userEvent.selectOptions(screen.getByLabelText("Source checklist for item 3"), "TRIPOD+AI");
    await userEvent.type(screen.getByLabelText("Source reference for item 3"), "9");
    await userEvent.click(screen.getByRole("button", { name: "Move Item 3 up" }));
    await userEvent.type(screen.getByLabelText("Change note"), "reference standard");
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    await waitFor(() => {
      const body = calls.find((c) => c.path === "/api/v1/reviewers/methodologist/versions")?.body as { items: unknown[]; base_version: number; note: string };
      expect(body.base_version).toBe(2);
      expect(body.note).toBe("reference standard");
      expect(body.items[1]).toEqual({ key: null, text: "The reference standard is described.", weight: 3, source: "TRIPOD+AI 9", pass_if: "yes", red_flag_if: "no" });
    });
  });

  it("refuses an invalid reviewer before calling the server", async () => {
    const { calls } = setup("admin", "/settings/reviewers/methodologist");
    await userEvent.clear(await screen.findByLabelText("Name"));
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Give the reviewer a name.");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows a stale save and the in_default_panel refusal in words", async () => {
    setup("admin", "/settings/reviewers/methodologist", {
      "POST /api/v1/reviewers/methodologist/versions": { status: 409, body: { code: "stale_version", message: "This reviewer changed since you opened it (now v3)", request_id: "r" } },
      "POST /api/v1/reviewers/methodologist/archive": { status: 409, body: { code: "in_default_panel", message: "Remove this reviewer from the default panel first", request_id: "r" } },
    });
    await userEvent.type(await screen.findByLabelText("Name"), "!");
    await userEvent.click(screen.getByRole("button", { name: "Save as v3" }));
    expect(await screen.findByText(/changed since you opened it/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Archive" }));
    expect(await screen.findByText("Remove this reviewer from the default panel first")).toBeInTheDocument();
  });

  it("Reset to default loads the shipped checklist", async () => {
    setup("admin", "/settings/reviewers/methodologist");
    await userEvent.click(await screen.findByRole("button", { name: "Reset to default" }));
    expect(screen.getByLabelText("Question for item 1 text")).toHaveValue("Default item.");
    expect(screen.queryByLabelText("Question for item 2 text")).not.toBeInTheDocument();
  });

  it("creates a new reviewer", async () => {
    const { calls } = setup("admin", "/settings/reviewers/new", { "POST /api/v1/reviewers": { status: 201, body: reviewerOut("radiologist", "Radiologist") } });
    await userEvent.type(await screen.findByLabelText("Name"), "Radiologist");
    await userEvent.type(screen.getByLabelText("Perspective"), "You judge image quality and protocols.");
    await userEvent.type(screen.getByLabelText("Question for item 1 text"), "Acquisition parameters are reported.");
    await userEvent.click(screen.getByRole("button", { name: "Create reviewer" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/v1/reviewers" && c.method === "POST")?.body).toMatchObject({ name: "Radiologist", items: [{ text: "Acquisition parameters are reported.", source: "CLAIM" }] }));
  });

  it("is read-only for viewers", async () => {
    setup("viewer", "/settings/reviewers/methodologist");
    expect(await screen.findByLabelText("Name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Save/ })).not.toBeInTheDocument();
  });
});

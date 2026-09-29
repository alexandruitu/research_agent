import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { fieldDetail, FIELD_ID, legacyField, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { FieldsPage } from "./FieldsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const LEGACY_ID = "12121212-1212-4212-8212-121212121212";
const ARCHIVED = { ...fieldDetail({ id: "34343434-3434-4434-8434-343434343434", name: "Old field", archived_at: "2026-09-27T10:00:00Z" }) };

function setup(role: "viewer" | "member" = "member") {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/fields": ({ url }) => ({
      body: url.searchParams.get("archived") === "true"
        ? [fieldDetail(), { ...legacyField(), id: LEGACY_ID, name: "Legacy topic" }, ARCHIVED]
        : [fieldDetail(), { ...legacyField(), id: LEGACY_ID, name: "Legacy topic" }],
    }),
  });
  renderWithProviders(<FieldsPage />);
  return api;
}

describe("FieldsPage", () => {
  it("lists fields with version, criteria, sources, last run and Start run", async () => {
    setup();
    const row = (await screen.findAllByRole("row")).find((r) => r.textContent?.includes("ML CT-FFR"))!;
    expect(row).toHaveTextContent("v2 · Mia Member");
    expect(row).toHaveTextContent("2 incl · 1 excl");
    expect(row).toHaveTextContent("Europe PMC");
    expect(row).toHaveTextContent("done · research · v2");
    expect(within(row).getByRole("link", { name: "Start run for ML CT-FFR" })).toHaveAttribute("href", `/runs?field=${FIELD_ID}`);
    expect(within(row).getByRole("link", { name: "ML CT-FFR" })).toHaveAttribute("href", `/fields/${FIELD_ID}`);
    expect(screen.getByRole("row", { name: /Legacy topic/ })).toHaveTextContent("topic match (legacy)");
    expect(screen.getByRole("link", { name: "New field" })).toHaveAttribute("href", "/fields/new");
  });

  it("shows archived fields on request, without Start run", async () => {
    const { calls } = setup();
    await screen.findByRole("table");
    expect(screen.queryByText("Old field")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "Show archived fields" }));
    const row = await screen.findByRole("row", { name: /Old field/ });
    expect(row).toHaveTextContent("archived");
    expect(within(row).queryByRole("link", { name: /Start run/ })).not.toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.search.includes("archived=true"))).toBe(true));
  });

  it("viewers read the list but cannot create fields or start runs", async () => {
    setup("viewer");
    await screen.findByRole("table");
    expect(screen.queryByRole("link", { name: "New field" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Start run/ })).not.toBeInTheDocument();
  });
});

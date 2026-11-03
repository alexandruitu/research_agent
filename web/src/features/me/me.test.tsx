import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../../api/client";
import type { KeyOut, MyModelsOut } from "../../api/types";
import { LoginPage } from "../../pages/LoginPage";
import { SignupPage } from "../../pages/SignupPage";
import { jobOut, session } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { MyKeysTab } from "./MyKeysTab";
import { MyModelsTab } from "./MyModelsTab";
import { MyUsageTab } from "./MyUsageTab";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const key = (over: Partial<KeyOut>): KeyOut => ({
  provider: "anthropic", label: "Anthropic (Claude)", kind: "model", saved: false, last4: null, created_at: null,
  checked_at: null, check_ok: null, check_detail: "", checkable: true, ...over,
});

const keys = (saved: boolean): KeyOut[] => [
  key(saved ? { saved: true, last4: "9c3a", created_at: "2026-11-01T10:00:00Z" } : {}),
  key({ provider: "openai", label: "OpenAI (GPT)" }),
  key({ provider: "typesafe", label: "TypeSafe (Jev)", kind: "jev", checkable: false }),
  key({ provider: "ieee", label: "IEEE Xplore", kind: "source", checkable: false }),
];

describe("My keys status chip", () => {
  it("marks a saved key and a dev server key in green words; nothing for a missing key", async () => {
    mockApi({ "GET /api/v1/me/keys": { body: [
      key({ saved: true, last4: "9c3a", created_at: "2026-11-01T10:00:00Z" }),
      key({ provider: "typesafe", label: "TypeSafe (Jev)", kind: "jev", checkable: false, server_key: true }),
      key({ provider: "openai", label: "OpenAI (GPT)" }),
    ] } });
    renderWithProviders(<MyKeysTab />);
    const models = await screen.findByRole("table", { name: "AI models" });
    expect(within(models).getByText("✓ Saved")).toHaveClass("chip--ok");
    expect(within(screen.getByRole("table", { name: "Screening tier (Jev)" })).getByText("✓ Server key (dev)")).toHaveClass("chip--ok");
    expect(within(models).getAllByText(/✓/)).toHaveLength(1);
  });
});

describe("Login → Create an account", () => {
  it("shows the link only when sign-up is open", async () => {
    mockApi({ "GET /api/v1/auth/me": { status: 401, body: {} }, "GET /api/v1/auth/signup": { body: { open: true } } });
    renderWithProviders(<Routes><Route path="/login" element={<LoginPage />} /></Routes>, { route: "/login" });
    expect(await screen.findByRole("link", { name: "Create an account" })).toHaveAttribute("href", "/signup");
  });

  it("hides the link when sign-up is off", async () => {
    mockApi({ "GET /api/v1/auth/me": { status: 401, body: {} }, "GET /api/v1/auth/signup": { body: { open: false } } });
    renderWithProviders(<Routes><Route path="/login" element={<LoginPage />} /></Routes>, { route: "/login" });
    await screen.findByRole("heading", { name: "Sign in" });
    await waitFor(() => expect(screen.queryByRole("link", { name: "Create an account" })).not.toBeInTheDocument());
  });

  it("signs up and shows the server's generic message; checks the password length first", async () => {
    const api = mockApi({
      "GET /api/v1/auth/me": { status: 401, body: {} },
      "GET /api/v1/auth/signup": { body: { open: true } },
      "POST /api/v1/auth/signup": { status: 202, body: { message: "If this address can be used, its account is ready." } },
    });
    renderWithProviders(<Routes><Route path="/signup" element={<SignupPage />} /></Routes>, { route: "/signup" });
    await userEvent.type(await screen.findByLabelText("Work email"), "ana@company.example");
    await userEvent.type(screen.getByLabelText("Name"), "Ana");
    await userEvent.type(screen.getByLabelText(/^Password/), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByRole("alert")).toHaveTextContent("at least 12 characters");
    await userEvent.type(screen.getByLabelText(/^Password/), " but now long enough");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("status")).toHaveTextContent("If this address can be used");
    expect(api.calls.find((c) => c.method === "POST")?.body).toEqual({ email: "ana@company.example", name: "Ana", password: "short but now long enough" });
  });

  it("shows a refused domain in plain words", async () => {
    mockApi({
      "GET /api/v1/auth/me": { status: 401, body: {} },
      "GET /api/v1/auth/signup": { body: { open: true } },
      "POST /api/v1/auth/signup": { status: 422, body: { code: "domain_not_allowed", message: "Use your work email address to create an account.", request_id: "r" } },
    });
    renderWithProviders(<Routes><Route path="/signup" element={<SignupPage />} /></Routes>, { route: "/signup" });
    await userEvent.type(await screen.findByLabelText("Work email"), "ana@gmail.example");
    await userEvent.type(screen.getByLabelText("Name"), "Ana");
    await userEvent.type(screen.getByLabelText(/^Password/), "a long enough password");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Use your work email address");
  });
});

describe("Settings → My keys", () => {
  it("saves a key, never shows it again, and offers test and delete", async () => {
    let saved = false;
    const api = mockApi({
      "GET /api/v1/auth/me": { body: session("member") },
      "GET /api/v1/me/keys": () => ({ body: keys(saved) }),
      "GET /api/v1/me/models": { body: { roles: [], options: [] } },
      "PUT /api/v1/me/keys/anthropic": () => {
        saved = true;
        return { body: keys(true)[0] };
      },
      "POST /api/v1/me/keys/anthropic/check": { status: 202, body: jobOut({ kind: "secret_check", run_id: null }) },
      "GET /api/v1/jobs/:id": { body: jobOut({ kind: "secret_check", status: "done", run_id: null }) },
      "DELETE /api/v1/me/keys/anthropic": { status: 204 },
    });
    renderWithProviders(<MyKeysTab />);
    const models = await screen.findByRole("table", { name: "AI models" });
    expect(within(screen.getByRole("table", { name: "Search sources" })).getByText("IEEE Xplore")).toBeInTheDocument();
    const input = within(models).getByLabelText("Anthropic (Claude) key");
    expect(input).toHaveAttribute("type", "password");
    await userEvent.type(input, "sk-ant-secret-9c3a");
    await userEvent.click(within(models).getByRole("button", { name: "Save Anthropic (Claude) key" }));
    expect(await within(models).findByText(/Saved …9c3a/)).toBeInTheDocument();
    expect(screen.queryByDisplayValue("sk-ant-secret-9c3a")).not.toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "PUT")?.body).toEqual({ key: "sk-ant-secret-9c3a" });
    await userEvent.click(within(models).getByRole("button", { name: "Test Anthropic (Claude) key" }));
    await userEvent.click(within(models).getByRole("button", { name: "Delete Anthropic (Claude) key" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(api.calls.some((c) => c.path === "/api/v1/me/keys/anthropic/check")).toBe(true);
  });
});

const modelsOut = (over: Partial<MyModelsOut> = {}): MyModelsOut => ({
  roles: [
    { role: "screen", label: "Screen", default: "anthropic:claude-sonnet-5", choice: null, effective: "anthropic:claude-sonnet-5" },
    { role: "review:methods", label: "Methods reviewer", default: null, choice: null, effective: null },
  ],
  options: [
    { id: "anthropic:claude-sonnet-5", provider: "anthropic", available: true },
    { id: "openai:gpt-5", provider: "openai", available: false },
  ],
  ...over,
});

describe("Settings → My models", () => {
  it("offers only models of providers with a key and saves the choices", async () => {
    const api = mockApi({
      "GET /api/v1/auth/me": { body: session("member") },
      "GET /api/v1/me/models": { body: modelsOut() },
      "PUT /api/v1/me/models": ({ body }) => ({ body: modelsOut({ roles: modelsOut().roles.map((r) => ({ ...r, choice: (body as { models: Record<string, string | null> }).models[r.role] ?? null })) }) }),
    });
    renderWithProviders(<MyModelsTab />);
    const screenSelect = await screen.findByLabelText("Screen");
    expect(within(screenSelect).getByRole("option", { name: /OpenAI · gpt-5 \(add a key first\)/ })).toBeDisabled();
    expect(within(screenSelect).getByRole("option", { name: "Default (anthropic:claude-sonnet-5)" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Methods reviewer"), "anthropic:claude-sonnet-5");
    await userEvent.click(screen.getByRole("button", { name: "Save my models" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Your next search uses these models");
    expect(api.calls.find((c) => c.method === "PUT")?.body).toEqual({ models: { screen: null, "review:methods": "anthropic:claude-sonnet-5" } });
  });

  it("says to add a key first when none is usable", async () => {
    mockApi({
      "GET /api/v1/auth/me": { body: session("member") },
      "GET /api/v1/me/models": { body: modelsOut({ options: [{ id: "openai:gpt-5", provider: "openai", available: false }] }) },
    });
    renderWithProviders(<MyModelsTab />);
    expect(await screen.findByText(/add one in Settings → My keys/)).toBeInTheDocument();
  });
});

describe("Settings → My usage", () => {
  it("lists months with calls and an estimated cost", async () => {
    mockApi({
      "GET /api/v1/auth/me": { body: session("member") },
      "GET /api/v1/me/usage": {
        body: { estimate: true, months: [{ month: "2026-10", runs: 2, calls: 40, cost_usd: 1.234, unpriced_models: ["made-up"] }] },
      },
    });
    renderWithProviders(<MyUsageTab />);
    const row = await screen.findByRole("row", { name: /2026-10/ });
    expect(row).toHaveTextContent("2");
    expect(row).toHaveTextContent("40");
    expect(row).toHaveTextContent("$1.23 (estimate)");
    expect(row).toHaveTextContent("no price for made-up");
  });

  it("explains an empty month list", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("member") }, "GET /api/v1/me/usage": { body: { estimate: true, months: [] } } });
    renderWithProviders(<MyUsageTab />);
    expect(await screen.findByText(/No searches yet/)).toBeInTheDocument();
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { session, userRows } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { UsersPage } from "./UsersPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(extra: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({ "GET /api/v1/auth/me": { body: session("admin") }, "GET /api/v1/users": { body: userRows() }, ...extra });
  renderWithProviders(<UsersPage />);
  return api;
}

describe("UsersPage", () => {
  it("lists users with role and whether the account is active", async () => {
    setup();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("member@example.org")).toBeInTheDocument();
    expect(within(table).getByText("inactive")).toBeInTheDocument();
    expect(within(table).getByRole("combobox", { name: "Role for member@example.org" })).toHaveValue("member");
  });

  it("changes a role and reloads the list", async () => {
    const { calls } = setup({ "PATCH /api/v1/users/:id": { body: { ...userRows()[1], role: "viewer" } } });
    await userEvent.selectOptions(await screen.findByRole("combobox", { name: "Role for member@example.org" }), "viewer");
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ role: "viewer" }));
    expect(calls.filter((c) => c.method === "GET" && c.path === "/api/v1/users").length).toBeGreaterThan(1);
  });

  it("deactivates and reactivates an account", async () => {
    const { calls } = setup({ "PATCH /api/v1/users/:id": { body: userRows()[1] } });
    await userEvent.click(await screen.findByRole("button", { name: "Deactivate member@example.org" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ active: false }));
    await userEvent.click(screen.getByRole("button", { name: "Reactivate old@example.org" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH").at(-1)?.body).toEqual({ active: true }));
  });

  it("shows the server's reason when the last admin cannot be changed", async () => {
    // The message and code are the backend's (routers/users.py) for demoting or deactivating the last active admin.
    setup({ "PATCH /api/v1/users/:id": { status: 409, body: { code: "last_admin", message: "There must be at least one active admin", request_id: "r" } } });
    await userEvent.click(await screen.findByRole("button", { name: "Deactivate admin@example.org" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least one active admin");
  });

  it("invites a user and refuses a short password before calling the server", async () => {
    const { calls } = setup({ "POST /api/v1/users": { status: 201, body: userRows()[1] } });
    await screen.findByRole("table");
    await userEvent.type(screen.getByLabelText("Email"), "new@example.org");
    await userEvent.type(screen.getByLabelText("Name"), "Nina New");
    await userEvent.type(screen.getByLabelText("Initial password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    expect(await screen.findByText("The password needs at least 12 characters.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.clear(screen.getByLabelText("Initial password"));
    await userEvent.type(screen.getByLabelText("Initial password"), "a-long-enough-password");
    await userEvent.selectOptions(screen.getByLabelText("Role"), "viewer");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ email: "new@example.org", name: "Nina New", role: "viewer", password: "a-long-enough-password" }));
    expect(screen.getByLabelText("Email")).toHaveValue("");
    expect(screen.getByLabelText("Initial password")).toHaveValue("");
  });

  it("shows a duplicate email as a message, not a crash", async () => {
    // The backend's message for a duplicate email (auth.create_user, returned with 409).
    setup({ "POST /api/v1/users": { status: 409, body: { code: "conflict", message: "email already registered", request_id: "r" } } });
    await screen.findByRole("table");
    await userEvent.type(screen.getByLabelText("Email"), "member@example.org");
    await userEvent.type(screen.getByLabelText("Name"), "Dup");
    await userEvent.type(screen.getByLabelText("Initial password"), "a-long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    expect(await screen.findByText(/already registered/)).toBeInTheDocument();
  });
});

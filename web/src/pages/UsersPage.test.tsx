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
  it("edits name and email in a dialog and sends only what changed", async () => {
    const { calls } = setup({ "PATCH /api/v1/users/:id": { body: userRows()[1] } });
    await userEvent.click(await screen.findByRole("button", { name: "Edit member@example.org" }));
    const dialog = screen.getByRole("dialog", { name: "Edit member@example.org" });
    const email = within(dialog).getByLabelText("Email");
    await userEvent.clear(email);
    await userEvent.type(email, "nope");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("valid email");
    await userEvent.clear(email);
    await userEvent.type(email, "Mia@Example.org");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ email: "Mia@Example.org" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("shows a duplicate email from the edit dialog", async () => {
    setup({ "PATCH /api/v1/users/:id": { status: 409, body: { code: "conflict", message: "email already registered", request_id: "r" } } });
    await userEvent.click(await screen.findByRole("button", { name: "Edit member@example.org" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.clear(within(dialog).getByLabelText("Email"));
    await userEvent.type(within(dialog).getByLabelText("Email"), "admin@example.org");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("already registered");
  });

  it("resets a password, refusing a short one first", async () => {
    const { calls } = setup({ "POST /api/v1/users/:id/password": { status: 204 } });
    await userEvent.click(await screen.findByRole("button", { name: "Reset password of member@example.org" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("New password"), "short");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set password" }));
    expect(within(dialog).getByRole("alert")).toHaveTextContent("at least 12");
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    await userEvent.clear(within(dialog).getByLabelText("New password"));
    await userEvent.type(within(dialog).getByLabelText("New password"), "a-long-enough-password");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set password" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")).toMatchObject({ path: `/api/v1/users/${userRows()[1].id}/password`, body: { password: "a-long-enough-password" } }));
    expect(await screen.findByText(/sessions were ended/)).toBeInTheDocument();
    expect(screen.queryByText("a-long-enough-password")).not.toBeInTheDocument();
  });

  it("says a referenced user will be anonymised and deletes only after the email is typed", async () => {
    const { calls } = setup({
      "GET /api/v1/users/:id/references": { body: { total: 3, by_table: { "runs.created_by": 3 }, outcome: "anonymize" } },
      "DELETE /api/v1/users/:id": { body: { outcome: "anonymized", user: null } },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Delete member@example.org" }));
    const dialog = screen.getByRole("dialog", { name: "Delete member@example.org" });
    expect(await within(dialog).findByText(/anonymised/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Delete user" });
    expect(confirm).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText(/to confirm/), "member@example.org");
    expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(await screen.findByText(/anonymised as “Deleted user”/)).toBeInTheDocument();
  });

  it("says an unreferenced user is deleted permanently", async () => {
    setup({ "GET /api/v1/users/:id/references": { body: { total: 0, by_table: {}, outcome: "delete" } } });
    await userEvent.click(await screen.findByRole("button", { name: "Delete old@example.org" }));
    expect(await within(screen.getByRole("dialog")).findByText(/deleted permanently/)).toBeInTheDocument();
  });

  it("offers no deactivate or delete on your own row, and lists deleted users on request", async () => {
    const me = { ...userRows()[0] };
    const deleted = { id: "10000000-0000-4000-8000-000000000009", email: "deleted-x@invalid", name: "Deleted user", role: "member", active: false, deleted_at: "2026-10-01T00:00:00Z" };
    const { calls } = setup({ "GET /api/v1/auth/me": { body: { user: me, csrf_token: "c" } }, "GET /api/v1/users": { body: [...userRows(), deleted] } });
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: "Delete admin@example.org" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deactivate admin@example.org" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit admin@example.org" })).toBeInTheDocument();
    expect(screen.getByText("deleted")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit deleted-x@invalid" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Show deleted"));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/v1/users" && c.search === "?include_deleted=true")).toBe(true));
  });
});

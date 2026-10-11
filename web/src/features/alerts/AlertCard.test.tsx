import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../../api/client";
import type { AlertOut } from "../../api/types";
import { FIELD_ID, JOB_ID, jobOut, RUN_ID, session } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { AlertCard, scheduleText } from "./AlertCard";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const ALERT_ID = "77777777-7777-4777-8777-777777777777";
const alertOut = (over: Partial<AlertOut> = {}): AlertOut => ({
  exists: true, id: ALERT_ID, field_id: FIELD_ID, enabled: true, cadence: "weekly", weekday: 0, hour: 7, timezone: "CEST",
  max_new: 50, effective_max_new: 50, min_group: "worth_a_look", years_back: 1, next_run_at: "2026-10-12T07:00:00+02:00",
  last_run_id: RUN_ID, last_run_status: "done", failures: 0, paused_reason: null, deferred_at: null,
  subscribed: true, subscriber_count: 2, created_by: null, can_edit: true, ...over,
});

function setup(alert: AlertOut, { role = "member" as "viewer" | "member" | "admin", demo = false } = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/fields/:id/alert": { body: alert },
    "PUT /api/v1/fields/:id/alert": ({ body }) => ({ body: { ...alert, ...(body as object), exists: true, id: ALERT_ID } }),
    "POST /api/v1/fields/:id/alert/run-now": { status: 202, body: { job: jobOut(), run_id: RUN_ID } },
    "DELETE /api/v1/alerts/:id/subscription": { body: { alert_id: ALERT_ID, subscribed: false } },
  });
  renderWithProviders(<AlertCard fieldId={FIELD_ID} archived={false} demo={demo} />);
  return api;
}

describe("AlertCard", () => {
  it("describes the schedule", () => {
    expect(scheduleText(alertOut())).toBe("Every Monday at 07:00 (CEST)");
    expect(scheduleText(alertOut({ cadence: "daily", hour: 18 }))).toBe("Every day at 18:00 (CEST)");
  });

  it("creates a new daily alert with the chosen settings", async () => {
    const api = setup(alertOut({ exists: false, id: null, enabled: false, subscriber_count: 0, subscribed: false, last_run_id: null, next_run_at: null }));
    await userEvent.selectOptions(await screen.findByLabelText(/Repeat/), "daily");
    expect(screen.queryByLabelText(/^On/)).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText(/Notify me about/), "read_first");
    const max = screen.getByLabelText(/Max new papers/);
    await userEvent.clear(max);
    await userEvent.type(max, "20");
    expect(screen.queryByRole("button", { name: "Run now" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save alert" }));
    await waitFor(() => expect(api.calls.find((c) => c.method === "PUT")?.body).toEqual({
      enabled: true, cadence: "daily", weekday: 0, hour: 7, max_new: 20, min_group: "read_first", years_back: 1,
    }));
  });

  it("shows the cap, a pause, the last run and follow state; Run now uses demo mode when chosen", async () => {
    const api = setup(alertOut({ max_new: 150, effective_max_new: 100, paused_reason: "3 failed runs in a row", failures: 3 }), { demo: true });
    expect(await screen.findByText(/Paused:/)).toBeInTheDocument();
    expect(screen.getByText(/reviews at most 100 papers per run/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "done" })).toHaveAttribute("href", `/screening/${RUN_ID}`);
    expect(screen.getByText(/2 people follow \(including you\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run now (demo)" }));
    await waitFor(() => expect(api.calls.find((c) => c.path.endsWith("/run-now"))?.body).toEqual({ mode: "demo" }));
    expect(api.calls.find((c) => c.path.endsWith("/run-now"))?.headers.get("Idempotency-Key")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Unfollow" }));
    await waitFor(() => expect(api.calls.some((c) => c.method === "DELETE")).toBe(true));
    expect(JOB_ID).toBeTruthy();
  });

  it("is read-only when the user cannot edit it", async () => {
    setup(alertOut({ can_edit: false }), { role: "viewer" });
    expect(await screen.findByText(/Read-only/)).toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.getByLabelText(/Max new papers/)).toBeDisabled();
    expect(screen.queryByRole("button", { name: /Save alert|Run now|Follow|Unfollow/ })).not.toBeInTheDocument();
  });
});

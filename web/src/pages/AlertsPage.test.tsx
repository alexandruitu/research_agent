import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import type { DigestOut } from "../api/types";
import { FIELD_ID, PAPER_ID, RUN_ID, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { AlertsPage, countsSentence } from "./AlertsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const DIGEST_ID = "88888888-8888-4888-8888-888888888888";
const digest = (over: Partial<DigestOut> = {}): DigestOut => ({
  id: DIGEST_ID, alert_id: "77777777-7777-4777-8777-777777777777", field_id: FIELD_ID, field_name: "ML CT-FFR", run_id: RUN_ID,
  status: "done", reason: null, created_at: "2026-10-08T07:00:00Z", read: false,
  counts: { found: 14, already_seen: 9, new: 5, over_cap: 2, reviewed: 3, in_digest: 1 },
  items: [{ paper_id: PAPER_ID, group: "read_first", why: "External validation on 3 sites.", title: "CT-FFR at scale", year: 2026 }],
  ...over,
});

function setup(digests: DigestOut[]) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session("member") },
    "GET /api/v1/digests": { body: { unread: digests.filter((d) => !d.read).length, digests } },
    "POST /api/v1/digests/:id/read": { body: { ...digests[0], read: true } },
  });
  renderWithProviders(<AlertsPage />);
  return api;
}

describe("AlertsPage", () => {
  it("writes the counts sentence", () => {
    expect(countsSentence({ found: 14, already_seen: 9, new: 5, over_cap: 2, deferred: true }, 2)).toEqual([
      "14 found · 9 already seen · 5 new · 2 worth reading",
      "2 more not reviewed — run the topic to see them.",
      "This run was deferred: the daily limit of alert runs was reached.",
    ]);
  });

  it("shows a digest with its papers and marks it read", async () => {
    const api = setup([digest()]);
    expect(await screen.findByRole("link", { name: "ML CT-FFR" })).toHaveAttribute("href", `/topics/${FIELD_ID}`);
    expect(screen.getByText("14 found · 9 already seen · 5 new · 1 worth reading")).toBeInTheDocument();
    expect(screen.getByText(/2 more not reviewed/)).toBeInTheDocument();
    expect(screen.getByText("Read first")).toBeInTheDocument();
    expect(screen.getByText("External validation on 3 sites.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open CT-FFR at scale" })).toHaveAttribute("href", `/results?run=${RUN_ID}&paper=${PAPER_ID}`);
    expect(screen.getByRole("link", { name: "Read CT-FFR at scale" })).toHaveAttribute("href", `/read/${RUN_ID}/${PAPER_ID}`);
    expect(screen.getByRole("button", { name: "Save to library: CT-FFR at scale" })).toBeInTheDocument();
    await waitFor(() => expect(api.calls.some((c) => c.method === "POST" && c.path.endsWith(`/digests/${DIGEST_ID}/read`))).toBe(true));
  });

  it("shows a failed run with its reason", async () => {
    setup([digest({ status: "failed", reason: "Europe PMC timed out", items: [], run_id: null, read: true })]);
    expect(await screen.findByText(/The alert run failed: Europe PMC timed out/)).toBeInTheDocument();
  });

  it("has an empty state", async () => {
    setup([]);
    expect(await screen.findByText("No alert digests yet")).toBeInTheDocument();
  });
});

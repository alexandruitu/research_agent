import { screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HUMAN_ID, PANEL_ID, compareOut, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { ComparePage } from "./ComparePage";

afterEach(() => vi.unstubAllGlobals());

function setup(result: { status?: number; body: unknown } = { body: compareOut() }) {
  const api = mockApi({ "GET /api/v1/auth/me": { body: session("viewer") }, "GET /api/v1/evals/compare": result });
  renderWithProviders(<Routes><Route path="/evals/compare" element={<ComparePage />} /></Routes>, { route: `/evals/compare?ids=${PANEL_ID},${HUMAN_ID}` });
  return api;
}

describe("Compare", () => {
  it("aligns metrics per report and says in words which rows differ", async () => {
    const { calls } = setup();
    const table = await screen.findByRole("table", { name: "Metrics side by side" });
    expect(calls.some((c) => c.search === `?ids=${encodeURIComponent(`${PANEL_ID},${HUMAN_ID}`)}`)).toBe(true);
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(expect.arrayContaining([expect.stringMatching(/Review panel/), expect.stringMatching(/Human reference/)]));
    const same = within(table).getByRole("row", { name: /Fleiss kappa/ });
    expect(same).toHaveTextContent("0.42");
    expect(same).toHaveTextContent("same");
    const diff = within(table).getByRole("row", { name: /Editor vs majority/ });
    expect(diff).toHaveTextContent("differs");
    expect(diff).toHaveClass("differs");
    expect(screen.getByRole("table", { name: "Configuration side by side" })).toHaveTextContent("demo");
    expect(screen.getByText(/2 of 3 rows differ/)).toBeInTheDocument();
  });

  it("shows the API's reason when the reports cannot be compared", async () => {
    setup({ status: 422, body: { code: "mixed_families", message: "Reports of different families cannot be compared", request_id: "r1" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("different families");
  });
});

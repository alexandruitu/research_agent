import { QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { createQueryClient } from "../api/queryClient";
import { App } from "../App";
import { STATISTICIAN } from "../features/validation/content";
import { session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function Where() {
  const { pathname, search, hash } = useLocation();
  return <output aria-label="location">{`${pathname}${search}${hash}`}</output>;
}

function renderApp(route: string) {
  mockApi({ "GET /api/v1/auth/me": { body: session("member") } });
  return render(
    <QueryClientProvider client={createQueryClient(false)}>
      <MemoryRouter initialEntries={[route]}>
        <App />
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const location = () => screen.getByRole("status", { hidden: true, name: "location" });

describe("Validation section", () => {
  it("opens on Evals and offers its three tabs, with Validation current in the main nav", async () => {
    renderApp("/validation");
    const tabs = await screen.findByRole("navigation", { name: "Validation sections" });
    expect(within(tabs).getAllByRole("link").map((l) => l.textContent)).toEqual(["Evals", "System map", "How it works"]);
    await waitFor(() => expect(within(screen.getByRole("navigation", { name: "Validation sections" })).getByRole("link", { name: "Evals" })).toHaveAttribute("aria-current", "page"));
    expect(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "Validation" })).toHaveAttribute("aria-current", "page");
    expect(location()).toHaveTextContent("/validation/evals");
  });

  it.each([
    ["/evals", "/validation/evals"],
    ["/evals/abc-123", "/validation/evals/abc-123"],
    ["/evals/compare?ids=a,b", "/validation/evals/compare?ids=a,b"],
    ["/evals/new", "/validation/evals/new"],
    ["/system?stage=reviewers", "/validation/system?stage=reviewers"],
  ])("redirects the old URL %s to %s", async (from, to) => {
    renderApp(from);
    await screen.findByRole("navigation", { name: "Validation sections" });
    await waitFor(() => expect(location()).toHaveTextContent(to));
  });

  it("explains how it works: flow, the four steps of an agent, the Statistician's items and the architecture", async () => {
    renderApp("/validation/how-it-works");
    expect(await screen.findByRole("heading", { level: 1, name: "How it works" })).toBeInTheDocument();
    const flow = screen.getByRole("list", { name: "Pipeline steps in order" });
    expect(within(flow).getByText("Screen")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Reviewers, in parallel" })).toHaveTextContent(/Statistician/);
    for (const step of ["Ask", "Answer", "Check", "Save"]) expect(screen.getByRole("heading", { level: 3, name: step })).toBeInTheDocument();
    const items = screen.getByRole("table", { name: /Statistician checklist/ });
    expect(within(items).getAllByRole("row")).toHaveLength(1 + 10);
    expect(within(items).getByRole("rowheader", { name: "s1" }).closest("tr")).toHaveTextContent("No confidence intervals for performance");
    expect(STATISTICIAN.items.map((i) => i.key)).toEqual(["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10"]);
    expect(screen.getByRole("heading", { level: 2, name: "4. Architecture" })).toBeInTheDocument();
  });
});

import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, setCsrfToken } from "../api/client";
import { createQueryClient } from "../api/queryClient";
import { App } from "../App";
import { session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { ErrorBoundary } from "./ErrorBoundary";
import { StaleBanner } from "./StaleBanner";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const unauthorized = { status: 401, body: { code: "unauthorized", message: "Sign in required", request_id: "r" } };

function renderApp(route: string) {
  return render(
    <QueryClientProvider client={createQueryClient(false)}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("routing and navigation", () => {
  it("sends anonymous visitors to the sign-in page", async () => {
    mockApi({ "GET /api/v1/auth/me": unauthorized });
    renderApp("/runs");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the main navigation, the user and a skip link", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("member") } });
    renderApp("/");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    for (const name of ["Papers", "Runs", "Evals", "System map"]) expect(nav).toHaveTextContent(name);
    expect(nav).not.toHaveTextContent("Users");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByText("Member")).toBeInTheDocument();
  });

  it("offers the Users page to admins only", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("admin") } });
    renderApp("/");
    expect(await screen.findByRole("link", { name: "Users" })).toBeInTheDocument();
  });

  it("blocks the Users route for members", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("member") } });
    renderApp("/users");
    expect(await screen.findByRole("heading", { name: "Not allowed" })).toBeInTheDocument();
  });

  it("signs out and returns to the sign-in page", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("member") }, "POST /api/v1/auth/logout": { status: 204 } });
    renderApp("/");
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("ErrorBoundary", () => {
  it("contains a crash to its panel and lets the user retry", async () => {
    let explode = true;
    function Fragile() {
      if (explode) throw new Error("boom");
      return <p>recovered</p>;
    }
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    // React 18 in development replays the render error through a window "error" event; without
    // preventDefault jsdom reports it as uncaught and prints the stack even though the boundary caught it.
    const swallow = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", swallow);
    try {
      render(<ErrorBoundary label="the drawer"><Fragile /></ErrorBoundary>);
      expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong in the drawer");
      explode = false;
      await userEvent.click(screen.getByRole("button", { name: "Try again" }));
      expect(screen.getByText("recovered")).toBeInTheDocument();
    } finally {
      window.removeEventListener("error", swallow);
      consoleError.mockRestore();
    }
  });
});

describe("StaleBanner", () => {
  it("appears when a refetch fails after data was shown, and disappears when it succeeds again", async () => {
    let failing = false;
    mockApi({ "GET /api/v1/ping": () => (failing ? { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "r" } } : { body: { ok: true } }) });
    const client = createQueryClient(false); // no retries: the failing refetch must surface immediately
    function Probe() {
      const query = useQuery({ queryKey: ["ping"], queryFn: () => api.get("/ping") });
      return <button onClick={() => query.refetch()}>refetch</button>;
    }
    render(
      <QueryClientProvider client={client}>
        <StaleBanner />
        <Probe />
      </QueryClientProvider>,
    );
    await waitFor(() => expect(client.getQueryData(["ping"])).toEqual({ ok: true }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    failing = true;
    await userEvent.click(screen.getByRole("button", { name: "refetch" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Data may be out of date");
    failing = false;
    await userEvent.click(screen.getByRole("button", { name: "refetch" }));
    await waitFor(() => expect(screen.queryByRole("status")).not.toBeInTheDocument());
  });
});

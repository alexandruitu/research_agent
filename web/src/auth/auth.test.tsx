import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, setCsrfToken } from "../api/client";
import { LoginPage } from "../pages/LoginPage";
import { session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { useAuth } from "./AuthProvider";
import { RequireAuth, RequireRole } from "./RequireAuth";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function Who() {
  const { status, user } = useAuth();
  return <p>{status}:{user?.email ?? "nobody"}</p>;
}

describe("AuthProvider", () => {
  it("restores an existing session and stores the CSRF token for later requests", async () => {
    const { calls } = mockApi({ "GET /api/v1/auth/me": { body: session("member") }, "POST /api/v1/x": { body: {} } });
    renderWithProviders(<Who />);
    expect(await screen.findByText("authenticated:member@example.org")).toBeInTheDocument();
    await api.post("/x");
    expect(calls.find((c) => c.path === "/api/v1/x")?.headers.get("X-CSRF-Token")).toBe("csrf-test");
  });

  it("is anonymous when there is no session", async () => {
    mockApi({ "GET /api/v1/auth/me": { status: 401, body: { code: "unauthorized", message: "Sign in required", request_id: "r" } } });
    renderWithProviders(<Who />);
    expect(await screen.findByText("anonymous:nobody")).toBeInTheDocument();
  });

  it("falls back to anonymous when any later request reports 401", async () => {
    mockApi({
      "GET /api/v1/auth/me": { body: session("member") },
      "GET /api/v1/runs": { status: 401, body: { code: "unauthorized", message: "Sign in required", request_id: "r" } },
    });
    renderWithProviders(<Who />);
    await screen.findByText("authenticated:member@example.org");
    await api.get("/runs").catch(() => undefined);
    expect(await screen.findByText("anonymous:nobody")).toBeInTheDocument();
  });
});

describe("LoginPage", () => {
  const unauthorized = { status: 401, body: { code: "unauthorized", message: "Sign in required", request_id: "r" } };

  it("signs in and shows the protected content", async () => {
    mockApi({
      "GET /api/v1/auth/me": unauthorized,
      "POST /api/v1/auth/login": (request) => (request.body as { password: string }).password === "correct horse battery" ? { body: session("admin") } : { status: 401, body: { code: "invalid_credentials", message: "Wrong email or password", request_id: "r" } },
    });
    renderWithProviders(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<p>secret page</p>} />
        </Route>
      </Routes>,
      { route: "/" },
    );
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument(); // redirected from "/"
    await userEvent.type(screen.getByLabelText("Email"), "admin@example.org");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("secret page")).toBeInTheDocument(); // sent back where the user was going
  });

  it("shows the server's message for wrong credentials and keeps the form usable", async () => {
    mockApi({
      "GET /api/v1/auth/me": unauthorized,
      "POST /api/v1/auth/login": { status: 401, body: { code: "invalid_credentials", message: "Wrong email or password", request_id: "r" } },
    });
    renderWithProviders(<LoginPage />, { route: "/login" });
    await userEvent.type(await screen.findByLabelText("Email"), "a@b.c");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password");
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("says when sign-in is temporarily blocked", async () => {
    mockApi({
      "GET /api/v1/auth/me": unauthorized,
      "POST /api/v1/auth/login": { status: 429, body: { code: "rate_limited", message: "Too many attempts; try again later", request_id: "r" } },
    });
    renderWithProviders(<LoginPage />, { route: "/login" });
    await userEvent.type(await screen.findByLabelText("Email"), "a@b.c");
    await userEvent.type(screen.getByLabelText("Password"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts");
  });
});

describe("LoginPage redirect target", () => {
  const signedIn = (from: unknown) => {
    mockApi({ "GET /api/v1/auth/me": { body: session("member") } });
    renderWithProviders(
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<p>home</p>} />
        <Route path="/runs" element={<p>runs page</p>} />
        <Route path="*" element={<p>somewhere else</p>} />
      </Routes>,
      { route: { pathname: "/login", state: { from } } },
    );
  };

  it("returns to the page the user was going to", async () => {
    signedIn("/runs?x=1");
    expect(await screen.findByText("runs page")).toBeInTheDocument();
  });

  it.each(["//evil.example/x", "/\\evil.example", "https://evil.example", "runs", 42])("goes home instead of to %s", async (from) => {
    signedIn(from);
    expect(await screen.findByText("home")).toBeInTheDocument();
  });
});

describe("RequireRole", () => {
  it("blocks users below the required role with an explanation", async () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("member") } });
    renderWithProviders(
      <Routes>
        <Route element={<RequireAuth />}>
          <Route element={<RequireRole role="admin" />}>
            <Route path="/" element={<p>admin area</p>} />
          </Route>
        </Route>
      </Routes>,
    );
    await waitFor(() => expect(screen.getByRole("heading", { name: "Not allowed" })).toBeInTheDocument());
    expect(screen.queryByText("admin area")).not.toBeInTheDocument();
  });
});

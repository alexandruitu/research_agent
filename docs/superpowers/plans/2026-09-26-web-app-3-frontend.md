# Web app 3 of 3: the React frontend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React + TypeScript single-page app for the department: sign-in, the Papers table with the pipeline strip and paper drawer, Runs (start, follow, resume), Evals (recall intervals and the threshold grid), the System map, and Users; plus the nginx image, end-to-end and accessibility tests, and CI.

**Architecture:** A Vite + React 18 + TypeScript app in `web/`. It talks only to the FastAPI JSON API under `/api/v1` with cookies and a CSRF header; its types are generated from the API's OpenAPI schema (`research-web openapi` → `openapi-typescript`), so frontend and backend cannot drift. TanStack Query owns server state; URL search parameters own view state (which run, filters, sort, page, open paper), so every view is linkable. Status is never conveyed by color alone (text labels and a hatched pattern). Spec: `docs/superpowers/specs/2026-09-26-web-app-slice1-design.md`. Plans 1 (backend) and 2 (worker, deployment) must be complete first; the mockups this plan implements were approved during brainstorming (paper table with pipeline strip and drawer, Evals page, System map).

**Tech Stack:** Node (the development Mac has Node 25 / npm 11), Vite 5, React 18, TypeScript 5.6 (strict), React Router 6, TanStack Query 5, Vitest 2 + Testing Library + jsdom, ESLint 9, `openapi-typescript` 7, Playwright + `@axe-core/playwright`, nginx for the production image. If `npm install` reports a peer-dependency conflict with these majors, use the newest mutually compatible versions and record the change in the commit message.

**Environment facts**
- The backend for development and end-to-end tests is `research-web dev` (embedded PostgreSQL via `pgserver`); there is no Docker on the development machine, so the `web` image and CI workflow are written and linted but **not executed here**.
- Never run a live-mode pipeline from a test or check (the child process would load the repository `.env`).
- A `.env` file with real API keys exists in the repo root: never read, print or commit it.

**Conventions used in every task**
- Frontend commands run in `web/` (`cd /Users/alexandruitu/Projects/research_agent/web`), Python commands from the repo root with the venv active. Branch: `feat/web-app`.
- After each task: `npm run typecheck && npm run lint && npm test` in `web/` must be green before committing.
- Commit with the trailer `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` as the second `-m`.
- Tests are TDD: write the failing test, watch it fail for the stated reason, implement, watch it pass.
- Accessibility rules for every component: real `button`/`a`/`table` semantics, visible focus, labels for inputs, status text next to color, no information in color alone.

## Contracts this plan relies on

- API base `/api/v1`; error body `{code, message, request_id, fields?}`; cookie session `ra_session` plus header `X-CSRF-Token` on every non-GET request (the token comes from `POST /auth/login` and `GET /auth/me`).
- Endpoints from plans 1 and 2: auth, users, fields, runs (+ `papers`, `papers/{id}`, `calls/{key}`, `POST /runs`, `resume`), jobs, imports, stages, evals, health.
- `PaperRow` cells: `null` = not applicable (a dash), `{"missing": true}` = expected data absent (hatched), never conflated.
- Stage `status` is one of `input | measured | caveat | unmeasured`; only `measured` renders green.

## File structure

| Path | Responsibility |
|---|---|
| `web/package.json`, `tsconfig.json`, `vite.config.ts`, `eslint.config.js`, `index.html` | tooling |
| `web/scripts/gen-api.mjs` | dump the OpenAPI schema and generate `src/api/schema.d.ts` |
| `web/src/api/client.ts` | `fetch` wrapper: cookies, CSRF, error shape, 401 event |
| `web/src/api/types.ts`, `schema.d.ts` | generated types and aliases |
| `web/src/api/hooks.ts` | TanStack Query hooks and query keys |
| `web/src/auth/*` | `AuthProvider`, `RequireAuth`, role helpers |
| `web/src/components/*` | layout, error boundary, stale banner, small shared pieces |
| `web/src/features/papers/*` | pipeline strip, table, cells, filters, drawer, stage panel, URL state |
| `web/src/features/runs/*`, `evals/*`, `system/*`, `users/*` | the other screens |
| `web/src/pages/*` | route components |
| `web/src/test/*` | `setup.ts`, `mockApi.ts`, `render.tsx`, `fixtures.ts` |
| `web/e2e/*`, `web/playwright.config.ts` | end-to-end and accessibility tests |
| `deploy/Dockerfile.web`, `deploy/nginx.conf`, `deploy/docker-compose.yml` (modify) | production image and the `web` service |
| `scripts/e2e_server.py`, `tests/test_web_e2e_server.py` | API + worker + synthetic dataset for the browser tests, and a test that guards that dataset |
| `src/research_agent/eval/report.py` (modify, Task 7) | store the holdout sweep so the Evals grid can flag risky pairs: the only backend change in this plan |
| `.github/workflows/ci.yml` | CI |

---

### Task 0: Scaffold the app and the test tooling

**Files:**
- Create: `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/eslint.config.js`, `web/index.html`, `web/.gitignore`, `web/src/main.tsx`, `web/src/App.tsx`, `web/src/styles.css`, `web/src/vite-env.d.ts`, `web/src/test/setup.ts`, `web/src/App.test.tsx`
- Modify: `.gitignore`

- [ ] **Step 1: Write `web/package.json`**

```json
{
  "name": "research-agent-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "typecheck": "tsc --noEmit",
    "lint": "eslint .",
    "test": "vitest run",
    "test:watch": "vitest",
    "gen:api": "node scripts/gen-api.mjs",
    "e2e": "playwright test"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.59.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.27.0"
  },
  "devDependencies": {
    "@axe-core/playwright": "^4.10.0",
    "@eslint/js": "^9.13.0",
    "@playwright/test": "^1.48.0",
    "@testing-library/jest-dom": "^6.6.0",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.11",
    "@types/react-dom": "^18.3.1",
    "@vitejs/plugin-react": "^4.3.3",
    "eslint": "^9.13.0",
    "eslint-plugin-react-hooks": "^5.0.0",
    "globals": "^15.11.0",
    "jsdom": "^25.0.1",
    "openapi-typescript": "^7.4.1",
    "typescript": "~5.6.3",
    "typescript-eslint": "^8.11.0",
    "vite": "^5.4.10",
    "vitest": "^2.1.3"
  }
}
```

- [ ] **Step 2: Write the configuration files**

`web/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "resolveJsonModule": true,
    "types": ["vite/client", "vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "e2e", "vite.config.ts", "playwright.config.ts"]
}
```

`web/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

`web/eslint.config.js`:

```js
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "playwright-report", "test-results", "src/api/schema.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks },
    rules: { ...reactHooks.configs.recommended.rules },
  },
);
```

`web/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Research Agent</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`web/.gitignore`:

```
node_modules
dist
playwright-report
test-results
```

Append `web/node_modules` to the repository `.gitignore`.

`web/src/vite-env.d.ts`: `/// <reference types="vite/client" />`

- [ ] **Step 3: Write the first failing test**

`web/src/App.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";

import { App } from "./App";

it("renders the app title", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Research Agent" })).toBeInTheDocument();
});
```

`web/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());
```

- [ ] **Step 4: Install and run to verify it fails**

Run: `cd web && npm install && npm test`
Expected: FAIL, `Failed to resolve import "./App"` (the component does not exist yet).

- [ ] **Step 5: Implement the minimal app**

`web/src/App.tsx`:

```tsx
export function App() {
  return <h1>Research Agent</h1>;
}
```

`web/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`web/src/styles.css` (design tokens; later tasks add component rules to this file):

```css
:root {
  --bg: #ffffff; --fg: #1f2933; --muted: #52606d; --line: #cbd2d9; --panel: #f5f7fa; --accent: #0f6e56;
  --focus: #1849a9;
  --ok-bg: #e1f5ee; --ok-fg: #085041; --ok-line: #1d9e75;
  --warn-bg: #faeeda; --warn-fg: #633806; --warn-line: #ba7517;
  --bad-bg: #fcebeb; --bad-fg: #791f1f; --bad-line: #e24b4a;
  --neutral-bg: #eceff1; --neutral-fg: #37474f;
  --font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #14181c; --fg: #e6eaee; --muted: #b0bac5; --line: #3b4550; --panel: #1c2228; --accent: #5dcaa5;
    --focus: #84a9ff;
    --ok-bg: #0c3b2e; --ok-fg: #9fe1cb; --ok-line: #1d9e75;
    --warn-bg: #46300c; --warn-fg: #fac775; --warn-line: #ba7517;
    --bad-bg: #4d1d1d; --bad-fg: #f7c1c1; --bad-line: #e24b4a;
    --neutral-bg: #2a333b; --neutral-fg: #d3dae0;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.5 var(--font); }
:focus-visible { outline: 3px solid var(--focus); outline-offset: 2px; }
```

- [ ] **Step 6: Run and commit**

Run: `npm run typecheck && npm run lint && npm test && npm run build`
Expected: all green; `dist/` is created (ignored by git).

```bash
cd .. && git add -A
git commit -m "Scaffold the React app with Vite, TypeScript strict, Vitest and ESLint" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 1: Generated API types and the fetch client

**Files:**
- Create: `web/scripts/gen-api.mjs`, `web/src/api/schema.d.ts` (generated), `web/src/api/types.ts`, `web/src/api/client.ts`, `web/src/test/mockApi.ts`
- Test: `web/src/api/client.test.ts`

- [ ] **Step 1: Write the generator script `web/scripts/gen-api.mjs`**

```js
// Dumps the API's OpenAPI schema with `research-web openapi` (venv must be active) and generates TypeScript types.
import { execFileSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import openapiTS, { astToString } from "openapi-typescript";

const out = join(mkdtempSync(join(tmpdir(), "research-agent-")), "openapi.json");
execFileSync("research-web", ["openapi", "-o", out], {
  stdio: "inherit",
  env: { ...process.env, RESEARCH_WEB_DATABASE_URL: process.env.RESEARCH_WEB_DATABASE_URL ?? "postgresql+psycopg://unused/unused" },
});
const ast = await openapiTS(pathToFileURL(out));
writeFileSync("src/api/schema.d.ts", "// GENERATED by `npm run gen:api` from `research-web openapi`. Do not edit.\n" + astToString(ast));
console.log("wrote src/api/schema.d.ts");
```

- [ ] **Step 2: Generate the types**

Run (from `web/`, venv active): `npm run gen:api`
Expected: `wrote src/api/schema.d.ts`; the file defines `components["schemas"]` including `PaperRow`, `PaperPage`, `DrawerOut`, `RunOut`, `RunDetailOut`, `StageOut`, `EvalSummaryOut`, `EvalDetailOut`, `JobOut`, `StartRunOut`, `UserOut`, `FieldOut`, `CallOut`. Commit it (a CI step will fail if it is stale).

- [ ] **Step 3: Write `web/src/api/types.ts`**

```ts
import type { components } from "./schema";

type S = components["schemas"];

export type UserOut = S["UserOut"];
export type SessionOut = S["SessionOut"];
export type FieldOut = S["FieldOut"];
export type RunOut = S["RunOut"];
export type RunDetailOut = S["RunDetailOut"];
export type RunCounts = S["RunCounts"];
export type PaperRow = S["PaperRow"];
export type PaperPage = S["PaperPage"];
export type DrawerOut = S["DrawerOut"];
export type CallOut = S["CallOut"];
export type StageOut = S["StageOut"];
export type EvalSummaryOut = S["EvalSummaryOut"];
export type EvalDetailOut = S["EvalDetailOut"];
export type JobOut = S["JobOut"];
export type StartRunOut = S["StartRunOut"];
export type ReviewOut = S["ReviewOut"];

export type Role = "viewer" | "member" | "admin";
export const ROLE_ORDER: Record<Role, number> = { viewer: 0, member: 1, admin: 2 };
export const hasRole = (user: { role: string } | null | undefined, minimum: Role): boolean =>
  !!user && (ROLE_ORDER[user.role as Role] ?? -1) >= ROLE_ORDER[minimum];
```

- [ ] **Step 4: Write the failing client tests**

`web/src/test/mockApi.ts` (shared by every later task):

```ts
import { vi } from "vitest";

export type MockResult = { status?: number; body?: unknown };
export type MockHandler = MockResult | ((request: { url: URL; method: string; body: unknown; headers: Headers }) => MockResult | Promise<MockResult>);
export type MockCall = { method: string; path: string; search: string; body: unknown; headers: Headers };

/** Replaces global fetch. Route keys look like "GET /api/v1/runs" or "GET /api/v1/runs/:id" (UUID segments become :id). */
export function mockApi(routes: Record<string, MockHandler>) {
  const calls: MockCall[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    calls.push({ method, path: url.pathname, search: url.search, body, headers });
    const generic = url.pathname.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g, ":id");
    const route = routes[`${method} ${url.pathname}`] ?? routes[`${method} ${generic}`];
    if (!route) {
      return new Response(JSON.stringify({ code: "not_found", message: `no mock for ${method} ${url.pathname}`, request_id: "test" }), { status: 404 });
    }
    const result = typeof route === "function" ? await route({ url, method, body, headers }) : route;
    const status = result.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(result.body ?? null), { status, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}
```

`web/src/api/client.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../test/mockApi";
import { ApiError, api, onUnauthorized, setCsrfToken } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

describe("api client", () => {
  it("sends cookies, builds the query string and skips empty parameters", async () => {
    const { fetchMock } = mockApi({ "GET /api/v1/runs": { body: [] } });
    await api.get("/runs", { kind: "eval", field_id: undefined, page: 2, flag: false, gone: null });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [URL, RequestInit];
    expect(url.pathname).toBe("/api/v1/runs");
    expect(url.search).toBe("?kind=eval&page=2&flag=false");
    expect(init.credentials).toBe("include");
  });

  it("adds the CSRF header to state-changing requests only", async () => {
    const { calls } = mockApi({ "GET /api/v1/x": { body: {} }, "POST /api/v1/x": { body: {} }, "PATCH /api/v1/x": { body: {} } });
    setCsrfToken("tok-1");
    await api.get("/x");
    await api.post("/x", { body: { a: 1 } });
    await api.patch("/x", { body: { b: 2 } });
    expect(calls.map((c) => c.headers.get("X-CSRF-Token"))).toEqual([null, "tok-1", "tok-1"]);
    expect(calls[1]?.headers.get("Content-Type")).toBe("application/json");
    expect(calls[1]?.body).toEqual({ a: 1 });
  });

  it("passes custom headers such as Idempotency-Key", async () => {
    const { calls } = mockApi({ "POST /api/v1/runs": { body: {} } });
    await api.post("/runs", { body: {}, headers: { "Idempotency-Key": "abc" } });
    expect(calls[0]?.headers.get("Idempotency-Key")).toBe("abc");
  });

  it("maps the API error shape to an ApiError", async () => {
    mockApi({ "POST /api/v1/users": { status: 422, body: { code: "validation_error", message: "Request validation failed", request_id: "r-9", fields: [{ loc: "body.email", message: "bad" }] } } });
    const error = await api.post("/users", { body: {} }).catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: "validation_error", requestId: "r-9", fields: [{ loc: "body.email", message: "bad" }] });
  });

  it("returns undefined for 204 and tolerates a non-JSON error body", async () => {
    mockApi({ "POST /api/v1/auth/logout": { status: 204 } });
    expect(await api.post("/auth/logout")).toBeUndefined();
    vi.stubGlobal("fetch", vi.fn(async () => new Response("Bad gateway", { status: 502 })));
    await expect(api.get("/runs")).rejects.toMatchObject({ status: 502, code: "error" });
  });

  it("announces 401 responses so the session state can reset", async () => {
    mockApi({ "GET /api/v1/runs": { status: 401, body: { code: "unauthorized", message: "Sign in required", request_id: "r" } } });
    const listener = vi.fn();
    const off = onUnauthorized(listener);
    await expect(api.get("/runs")).rejects.toBeInstanceOf(ApiError);
    expect(listener).toHaveBeenCalledTimes(1);
    off();
  });
});
```

- [ ] **Step 5: Run to verify failure**

Run: `npm test -- src/api/client.test.ts`
Expected: FAIL, `Failed to resolve import "./client"`.

- [ ] **Step 6: Implement `web/src/api/client.ts`**

```ts
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string,
    readonly fields?: { loc: string; message: string }[],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Params = Record<string, string | number | boolean | null | undefined>;
type Options = { body?: unknown; params?: Params; headers?: Record<string, string> };

let csrfToken: string | null = null;
const unauthorizedListeners = new Set<() => void>();

export const setCsrfToken = (token: string | null) => {
  csrfToken = token;
};

export const onUnauthorized = (listener: () => void) => {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
};

async function request<T>(method: string, path: string, options: Options = {}): Promise<T> {
  const url = new URL(`/api/v1${path}`, window.location.origin);
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
  }
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(url, {
    method,
    headers,
    credentials: "include",
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = undefined;
  }
  if (!response.ok) {
    const body = (data ?? {}) as { code?: string; message?: string; request_id?: string; fields?: { loc: string; message: string }[] };
    if (response.status === 401) unauthorizedListeners.forEach((listener) => listener());
    throw new ApiError(response.status, body.code ?? "error", body.message ?? (response.statusText || "Request failed"), body.request_id ?? "-", body.fields);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>("GET", path, { params }),
  post: <T>(path: string, options?: Options) => request<T>("POST", path, options),
  patch: <T>(path: string, options?: Options) => request<T>("PATCH", path, options),
};
```

- [ ] **Step 7: Run and commit**

Run: `npm run typecheck && npm run lint && npm test`
Expected: green (5 client tests).

```bash
cd .. && git add -A
git commit -m "Add generated API types and the fetch client with CSRF and error mapping" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Sign-in state and the login page

**Files:**
- Create: `web/src/auth/AuthProvider.tsx`, `web/src/auth/RequireAuth.tsx`, `web/src/pages/LoginPage.tsx`, `web/src/test/render.tsx`, `web/src/test/fixtures.ts`
- Test: `web/src/auth/auth.test.tsx`

- [ ] **Step 1: Create the shared test helpers**

`web/src/test/fixtures.ts` (extended by later tasks):

```ts
import type { UserOut } from "../api/types";

export const user = (role: "viewer" | "member" | "admin" = "member"): UserOut => ({
  id: "11111111-1111-4111-8111-111111111111",
  email: `${role}@example.org`,
  name: role[0]!.toUpperCase() + role.slice(1),
  role,
  active: true,
});

export const session = (role: "viewer" | "member" | "admin" = "member") => ({ user: user(role), csrf_token: "csrf-test" });
```

`web/src/test/render.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";

import { AuthProvider } from "../auth/AuthProvider";

export const testQueryClient = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });

/** Renders inside a query client, a router and the real AuthProvider (mock /auth/me with mockApi first). */
export function renderWithProviders(ui: ReactElement, { route = "/", client = testQueryClient() }: { route?: string; client?: QueryClient } = {}) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>
          <AuthProvider>{ui}</AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}
```

- [ ] **Step 2: Write the failing tests**

`web/src/auth/auth.test.tsx`:

```tsx
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
```

- [ ] **Step 3: Run to verify failure**

Run: `npm test -- src/auth/auth.test.tsx`
Expected: FAIL, `Failed to resolve import "./AuthProvider"`.

- [ ] **Step 4: Implement `web/src/auth/AuthProvider.tsx`**

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, onUnauthorized, setCsrfToken } from "../api/client";
import type { SessionOut, UserOut } from "../api/types";

type Status = "loading" | "anonymous" | "authenticated";
type AuthValue = {
  status: Status;
  user: UserOut | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ status: Status; user: UserOut | null }>({ status: "loading", user: null });
  const queryClient = useQueryClient();

  const adopt = useCallback((session: SessionOut | null) => {
    setCsrfToken(session?.csrf_token ?? null);
    setState(session ? { status: "authenticated", user: session.user } : { status: "anonymous", user: null });
  }, []);

  useEffect(() => {
    let cancelled = false;
    api.get<SessionOut>("/auth/me").then(
      (session) => !cancelled && adopt(session),
      () => !cancelled && adopt(null),
    );
    return () => {
      cancelled = true;
    };
  }, [adopt]);

  useEffect(() => onUnauthorized(() => adopt(null)), [adopt]);

  const value = useMemo<AuthValue>(
    () => ({
      ...state,
      login: async (email, password) => adopt(await api.post<SessionOut>("/auth/login", { body: { email, password } })),
      logout: async () => {
        await api.post("/auth/logout").catch(() => undefined);
        adopt(null);
        queryClient.clear();
      },
    }),
    [state, adopt, queryClient],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
```

`web/src/auth/RequireAuth.tsx`:

```tsx
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { hasRole, type Role } from "../api/types";
import { useAuth } from "./AuthProvider";

export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <p role="status">Loading…</p>;
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  return <Outlet />;
}

export function RequireRole({ role }: { role: Role }) {
  const { user } = useAuth();
  if (!hasRole(user, role)) {
    return (
      <section>
        <h1>Not allowed</h1>
        <p>Your role does not allow this page. Ask an administrator if you need access.</p>
      </section>
    );
  }
  return <Outlet />;
}
```

`web/src/pages/LoginPage.tsx`:

```tsx
import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";

export function LoginPage() {
  const { status, login } = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  if (status === "authenticated") return <Navigate to={from} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not reach the server. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="login">
      <h1>Sign in</h1>
      <form onSubmit={submit}>
        <label>
          Email
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Password
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p role="alert" className="form-error">{error}</p>}
        <button type="submit" disabled={busy}>Sign in</button>
      </form>
    </main>
  );
}
```

- [ ] **Step 5: Run and commit**

Run: `npm run typecheck && npm run lint && npm test`
Expected: green.

```bash
cd .. && git add -A
git commit -m "Add sign-in state, protected routes and the login page" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Layout, routing, error boundaries and the stale-data indicator

**Files:**
- Create: `web/src/components/Layout.tsx`, `web/src/components/ErrorBoundary.tsx`, `web/src/components/StaleBanner.tsx`, `web/src/api/queryClient.ts`, `web/src/pages/PlaceholderPages.tsx`
- Modify: `web/src/App.tsx`, `web/src/main.tsx`, `web/src/styles.css`, `web/src/App.test.tsx`
- Test: `web/src/components/layout.test.tsx`

- [ ] **Step 1: Write the failing tests**

`web/src/components/layout.test.tsx`:

```tsx
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
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<ErrorBoundary label="the drawer"><Fragile /></ErrorBoundary>);
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong in the drawer");
    explode = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(screen.getByText("recovered")).toBeInTheDocument();
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
```

Also replace `web/src/App.test.tsx` (the scaffold test no longer applies; the routing tests above cover `App`) with a single check that the title is present in the layout: delete the file.

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/components/layout.test.tsx`
Expected: FAIL, `Failed to resolve import "../api/queryClient"`.

- [ ] **Step 3: Implement the query client and stale store**

`web/src/api/queryClient.ts`:

```ts
import { QueryCache, QueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

let stale = false;
const listeners = new Set<() => void>();
const setStale = (value: boolean) => {
  if (stale === value) return;
  stale = value;
  listeners.forEach((listener) => listener());
};

export const useStale = () =>
  useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => stale,
  );

/** A failed refetch of data that was already on screen marks the page as possibly stale until any fetch succeeds. */
export function createQueryClient(retry: number | false = 1) {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (_error, query) => {
        if (query.state.data !== undefined) setStale(true);
      },
      onSuccess: () => setStale(false),
    }),
    defaultOptions: { queries: { retry, refetchOnWindowFocus: false, staleTime: 5_000 } },
  });
}
```

- [ ] **Step 4: Implement the components**

`web/src/components/ErrorBoundary.tsx`:

```tsx
import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { label: string; children: ReactNode };
type State = { failed: boolean };

/** Contains a render crash to one panel so the rest of the page keeps working. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`panel "${this.props.label}" crashed`, error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="panel-error">
        <p>Something went wrong in {this.props.label}.</p>
        <button type="button" onClick={() => this.setState({ failed: false })}>Try again</button>
      </div>
    );
  }
}
```

`web/src/components/StaleBanner.tsx`:

```tsx
import { useStale } from "../api/queryClient";

export function StaleBanner() {
  return useStale() ? <p role="status" className="stale-banner">Data may be out of date: the last refresh failed.</p> : null;
}
```

`web/src/components/Layout.tsx`:

```tsx
import { NavLink, Outlet } from "react-router-dom";

import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { ErrorBoundary } from "./ErrorBoundary";
import { StaleBanner } from "./StaleBanner";

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <>
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="topbar">
        <strong className="brand">Research Agent</strong>
        <nav aria-label="Main">
          <NavLink to="/" end>Papers</NavLink>
          <NavLink to="/runs">Runs</NavLink>
          <NavLink to="/evals">Evals</NavLink>
          <NavLink to="/system">System map</NavLink>
          {hasRole(user, "admin") && <NavLink to="/users">Users</NavLink>}
        </nav>
        <div className="who">
          <span>{user?.name}</span> <span className="role">{user?.role}</span>
          <button type="button" onClick={() => void logout()}>Sign out</button>
        </div>
      </header>
      <StaleBanner />
      <main id="main" tabIndex={-1}>
        <ErrorBoundary label="this page">
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  );
}
```

`web/src/pages/PlaceholderPages.tsx` (each later task replaces one of these with the real page):

```tsx
const page = (title: string) => () => (
  <section>
    <h1>{title}</h1>
  </section>
);

export const PapersPage = page("Papers");
export const RunsPage = page("Runs");
export const EvalsPage = page("Evals");
export const SystemMapPage = page("System map");
export const UsersPage = page("Users");
```

`web/src/App.tsx`:

```tsx
import { Route, Routes } from "react-router-dom";

import { RequireAuth, RequireRole } from "./auth/RequireAuth";
import { AuthProvider } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { LoginPage } from "./pages/LoginPage";
import { EvalsPage, PapersPage, RunsPage, SystemMapPage, UsersPage } from "./pages/PlaceholderPages";

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/" element={<PapersPage />} />
            <Route path="/runs" element={<RunsPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="/evals/:evalId" element={<EvalsPage />} />
            <Route path="/system" element={<SystemMapPage />} />
            <Route element={<RequireRole role="admin" />}>
              <Route path="/users" element={<UsersPage />} />
            </Route>
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
```

`web/src/main.tsx`:

```tsx
import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { createQueryClient } from "./api/queryClient";
import { App } from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={createQueryClient()}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
```

Append to `web/src/styles.css`:

```css
.skip-link { position: absolute; left: -999px; top: 0; background: var(--bg); padding: 8px 12px; z-index: 10; }
.skip-link:focus { left: 8px; top: 8px; }
.topbar { display: flex; align-items: center; gap: 24px; padding: 8px 16px; border-bottom: 1px solid var(--line); background: var(--panel); }
.topbar nav { display: flex; gap: 4px; flex: 1; }
.topbar nav a { padding: 6px 10px; border-radius: 6px; color: var(--fg); text-decoration: none; }
.topbar nav a[aria-current="page"] { background: var(--neutral-bg); font-weight: 600; box-shadow: inset 0 -2px 0 var(--accent); }
.who { display: flex; align-items: center; gap: 8px; color: var(--muted); }
.who .role { border: 1px solid var(--line); border-radius: 10px; padding: 0 8px; font-size: 12px; }
main { padding: 16px; max-width: 1400px; margin: 0 auto; }
h1 { font-size: 20px; margin: 0 0 12px; }
button { font: inherit; padding: 4px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); cursor: pointer; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
button[aria-pressed="true"] { background: var(--neutral-bg); border-color: var(--accent); font-weight: 600; }
.stale-banner { margin: 0; padding: 6px 16px; background: var(--warn-bg); color: var(--warn-fg); border-bottom: 1px solid var(--warn-line); }
.panel-error { padding: 12px; border: 1px solid var(--bad-line); background: var(--bad-bg); color: var(--bad-fg); border-radius: 6px; }
.login { max-width: 360px; margin: 10vh auto; }
.login form { display: grid; gap: 12px; }
.login label { display: grid; gap: 4px; }
input, select { font: inherit; padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); color: var(--fg); }
.form-error { color: var(--bad-fg); background: var(--bad-bg); border: 1px solid var(--bad-line); padding: 6px 8px; border-radius: 6px; margin: 0; }
```

- [ ] **Step 5: Run and commit**

Run: `npm run typecheck && npm run lint && npm test && npm run build`
Expected: green.

```bash
cd .. && git add -A
git commit -m "Add the layout, routing, panel error boundaries and the stale-data banner" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 4: Query hooks, fixtures and the Papers URL state

**Files:**
- Create: `web/src/api/hooks.ts`, `web/src/features/papers/papersState.ts`
- Modify: `web/src/test/fixtures.ts`
- Test: `web/src/features/papers/papersState.test.ts`

The view state (which run, page, sort, filters, open paper or stage) lives in URL search parameters so every view is linkable and the back button works. The parsing and patching rules are pure functions and are tested first.

- [ ] **Step 1: Extend the fixtures (append to `web/src/test/fixtures.ts`)**

Later tasks append more fixtures the same way. Each block starts with an `import type` line: move those lines to the top of the file, merging them with the existing import from `"../api/types"`.

```ts
import type { DrawerOut, PaperRow, RunDetailOut, RunOut, StageOut } from "../api/types";

export const RUN_ID = "22222222-2222-4222-8222-222222222222";
export const PAPER_ID = "33333333-3333-4333-8333-333333333333";
export const FIELD_ID = "44444444-4444-4444-8444-444444444444";

export const runOut = (over: Partial<RunOut> = {}): RunOut => ({
  id: RUN_ID, field_id: FIELD_ID, field_name: "ML CT-FFR", kind: "eval", status: "done",
  finished_at: "2026-09-26T09:00:00Z", created_at: "2026-09-26T08:00:00Z", gold_set_name: "mlffrct-2024",
  paper_count: 151, error: null, models: {}, ...over,
});

export const runDetail = (over: Partial<RunDetailOut> = {}): RunDetailOut => ({
  ...runOut(), manifest: {}, counts: { screened: 151, kept: 112, dropped: 39, escalated: 82, in_sr: 16 }, ...over,
});

const stage = (id: string, title: string, status: StageOut["status"], headline: string | null = null, over: Partial<StageOut> = {}): StageOut => ({
  id, title, summary: `${title} summary.`, limits: `${title} limits.`, status, headline, caveat: null, data_link: null, ...over,
});

export const STAGES: StageOut[] = [
  stage("topic", "Topic", "input"),
  stage("plan", "Plan", "unmeasured"),
  stage("search", "Search", "measured", "recall 15/16", { data_link: "evals" }),
  stage("dedup", "Deduplicate", "unmeasured"),
  stage("screen", "Screen", "measured", "recall 15/16", { data_link: "papers", summary: "Jev decides when confident; Claude screens the rest.", limits: "Abstract only." }),
  stage("extract", "Extract", "measured", "36 papers, quotes verified", { data_link: "papers" }),
  stage("reviewers", "Reviewers A and B", "caveat", "kappa 0.94", { caveat: "one model family", data_link: "evals" }),
  stage("adjudicate", "Adjudicate", "measured", "fired 1 of 36", { data_link: "papers" }),
  stage("rank", "Rank", "unmeasured", null, { data_link: "papers" }),
];

export const paperRow = (over: Partial<PaperRow> = {}): PaperRow => ({
  paper: { id: PAPER_ID, source_id: "MED:1", title: "Diagnostic accuracy of a deep learning approach to calculate FFR", year: 2019, doi: "10.1000/x" },
  found_by: "query", in_sr: true,
  screen: { tier: "jev", decision: "include", jev_decision: "include", llm_decision: null, criteria: { topic_match: 0.99 } },
  extract: { claims: 5, quotes_verified: true },
  reviews: { a: "include", b: "include", adjudicated: false, adjudicator: null },
  rank: { score: 82, position: 1 },
  ...over,
});

/** The real paper the screen lost: Jev 0.06 (just above the auto-drop line), dropped by the LLM, included by the SR. */
export const lostRow = (): PaperRow =>
  paperRow({
    paper: { id: "55555555-5555-4555-8555-555555555555", source_id: "MED:35097009", title: "Change in CT-Derived FFR Across the Lesion Improve the Diagnostic Performance", year: 2021, doi: "10.3389/fcvm.2021.788703" },
    found_by: "lookup", in_sr: true,
    screen: { tier: "llm", decision: "exclude", jev_decision: "escalate", llm_decision: "exclude", criteria: { topic_match: 0.06 } },
    extract: null, reviews: null, rank: null,
  });

export const drawerOut = (over: Partial<DrawerOut> = {}): DrawerOut => ({
  paper: { id: "55555555-5555-4555-8555-555555555555", source_id: "MED:35097009", title: "Change in CT-Derived FFR Across the Lesion Improve the Diagnostic Performance", abstract: "This study sought to evaluate the diagnostic performance of change in CT-FFR across the lesion.", year: 2021, doi: "10.3389/fcvm.2021.788703" },
  found_by: "lookup", in_sr: true, label_source: "sr_included_list",
  screening: {
    tier: "llm", decision: "exclude", jev_decision: "escalate", llm_decision: "exclude", call_key: "a".repeat(64),
    reason: "Jev topic_match=0.06 (Jev was not confident, so the LLM decided); LLM screen: exclude",
    criteria: [{ key: "topic_match", question: "The paper's central subject is the topic.", probability: 0.06, jev_version: "jev-1.13.0" }],
  },
  claims: [{ statement: "ΔCT-FFR improves specificity over CCTA.", quote: "ΔCT-FFR and CT-FFR were 70.8 and 67.4%", call_key: "b".repeat(64) }],
  reviews: [
    { role: "a", verdict: "uncertain", relevance: 2, methods: 2, support: 2, detail: { assessment: "Retrospective diagnostic accuracy study; the abstract does not name ML.", strengths: ["Reference standard is invasive FFR"], weaknesses: ["Small cohort"] }, call_key: "c".repeat(64) },
    { role: "b", verdict: "exclude", relevance: 1, methods: 2, support: 2, detail: { assessment: "No machine learning is mentioned.", strengths: [], weaknesses: ["Off topic on the abstract"] }, call_key: "d".repeat(64) },
    { role: "adjudicator", verdict: "uncertain", relevance: 2, methods: 2, support: 2, detail: { assessment: "Uncertainty preserved.", reason: "The abstract neither confirms nor rules out ML/DL-based CT-FFR." }, call_key: "e".repeat(64) },
  ],
  rank: null,
  ...over,
});
```

- [ ] **Step 2: Write the failing tests for the URL state**

`web/src/features/papers/papersState.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { PAGE_SIZE, parseView, patchView } from "./papersState";

const q = (text: string) => new URLSearchParams(text);

describe("parseView", () => {
  it("has sensible defaults", () => {
    const view = parseView(q(""));
    expect(view).toEqual({
      runId: null, paperId: null, stageId: null,
      params: { page: 1, page_size: PAGE_SIZE, sort: "title", direction: "asc" },
    });
  });

  it("reads every parameter", () => {
    const view = parseView(q("run=r1&page=3&sort=criterion:topic_match&dir=desc&decision=exclude&tier=jev&escalated=true&in_sr=false&pmin=0.4&pmax=0.6&paper=p1"));
    expect(view.runId).toBe("r1");
    expect(view.paperId).toBe("p1");
    expect(view.params).toEqual({
      page: 3, page_size: PAGE_SIZE, sort: "criterion:topic_match", direction: "desc", decision: "exclude", tier: "jev",
      escalated: true, in_sr: false, criterion: "topic_match", p_min: 0.4, p_max: 0.6,
    });
  });

  it("ignores values the API would reject", () => {
    const view = parseView(q("page=0&sort=drop table&dir=sideways&decision=maybe&tier=x&pmin=abc&pmax=2"));
    expect(view.params).toEqual({ page: 1, page_size: PAGE_SIZE, sort: "title", direction: "asc" });
  });
});

describe("patchView", () => {
  it("changing a filter, the sort or the run goes back to page 1", () => {
    expect(patchView(q("page=4&run=r1"), { decision: "exclude" }).get("page")).toBeNull();
    expect(patchView(q("page=4"), { sort: "year" }).get("page")).toBeNull();
    expect(patchView(q("page=4"), { run: "r2" }).get("page")).toBeNull();
    expect(patchView(q("page=4"), { page: 5 }, false).get("page")).toBe("5");
  });

  it("null removes a parameter and booleans are stored as text", () => {
    const next = patchView(q("decision=exclude&escalated=true"), { decision: null, in_sr: true });
    expect(next.toString()).toBe("escalated=true&in_sr=true");
  });

  it("a paper and a stage panel are mutually exclusive, and changing the run closes both", () => {
    expect(patchView(q("stage=screen"), { paper: "p1" }, false).toString()).toBe("paper=p1");
    expect(patchView(q("paper=p1"), { stage: "screen" }, false).toString()).toBe("stage=screen");
    expect(patchView(q("paper=p1&run=r1"), { run: "r2" }).toString()).toBe("run=r2");
  });

  it("does not mutate the input", () => {
    const original = q("page=2");
    patchView(original, { page: 3 }, false);
    expect(original.toString()).toBe("page=2");
  });
});
```

- [ ] **Step 3: Run to verify failure**

Run: `npm test -- src/features/papers/papersState.test.ts`
Expected: FAIL, `Failed to resolve import "./papersState"`.

- [ ] **Step 4: Implement the hooks (`web/src/api/hooks.ts`) and the URL state**

`web/src/api/hooks.ts`:

```ts
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { CallOut, DrawerOut, EvalDetailOut, EvalSummaryOut, FieldOut, JobOut, PaperPage, RunDetailOut, RunOut, StageOut, StartRunOut, UserOut } from "./types";

export type PaperParams = {
  page: number; page_size: number; sort: string; direction: "asc" | "desc";
  decision?: string; tier?: string; escalated?: boolean; in_sr?: boolean; criterion?: string; p_min?: number; p_max?: number;
};

export const keys = {
  fields: ["fields"] as const,
  runs: ["runs"] as const,
  run: (id: string) => ["run", id] as const,
  papers: (runId: string, params: PaperParams) => ["papers", runId, params] as const,
  paper: (runId: string, paperId: string) => ["paper", runId, paperId] as const,
  stages: ["stages"] as const,
  evals: ["evals"] as const,
  eval: (id: string) => ["eval", id] as const,
  job: (id: string) => ["job", id] as const,
  call: (runId: string, key: string) => ["call", runId, key] as const,
  users: ["users"] as const,
};

export const newIdempotencyKey = () =>
  globalThis.crypto?.randomUUID?.() ?? `k-${Date.now()}-${Math.random().toString(16).slice(2)}`;

export const useFields = () => useQuery({ queryKey: keys.fields, queryFn: () => api.get<FieldOut[]>("/fields") });
export const useRuns = () => useQuery({ queryKey: keys.runs, queryFn: () => api.get<RunOut[]>("/runs") });
export const useRun = (id: string | null) =>
  useQuery({ queryKey: keys.run(id ?? ""), enabled: !!id, queryFn: () => api.get<RunDetailOut>(`/runs/${id}`) });
export const usePapers = (runId: string | null, params: PaperParams) =>
  useQuery({
    queryKey: keys.papers(runId ?? "", params), enabled: !!runId, placeholderData: keepPreviousData,
    queryFn: () => api.get<PaperPage>(`/runs/${runId}/papers`, params),
  });
export const usePaper = (runId: string | null, paperId: string | null) =>
  useQuery({ queryKey: keys.paper(runId ?? "", paperId ?? ""), enabled: !!runId && !!paperId, queryFn: () => api.get<DrawerOut>(`/runs/${runId}/papers/${paperId}`) });
export const useStages = () => useQuery({ queryKey: keys.stages, queryFn: () => api.get<StageOut[]>("/stages") });
export const useEvals = () => useQuery({ queryKey: keys.evals, queryFn: () => api.get<EvalSummaryOut[]>("/evals") });
export const useEval = (id: string | null) =>
  useQuery({ queryKey: keys.eval(id ?? ""), enabled: !!id, queryFn: () => api.get<EvalDetailOut>(`/evals/${id}`) });
export const useCall = (runId: string, key: string | null) =>
  useQuery({ queryKey: keys.call(runId, key ?? ""), enabled: !!key, retry: false, queryFn: () => api.get<CallOut>(`/runs/${runId}/calls/${key}`) });
export const useUsers = () => useQuery({ queryKey: keys.users, queryFn: () => api.get<UserOut[]>("/users") });

/** Polls every 2 seconds while the job is queued or running. */
export const useJob = (id: string | null) =>
  useQuery({
    queryKey: keys.job(id ?? ""), enabled: !!id, queryFn: () => api.get<JobOut>(`/jobs/${id}`),
    refetchInterval: (query) => (["queued", "running"].includes(query.state.data?.status ?? "") ? 2000 : false),
  });

export function useStartRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { field_id: string; max_papers: number; mode: "live" | "demo" }) =>
      api.post<StartRunOut>("/runs", { body, headers: { "Idempotency-Key": newIdempotencyKey() } }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runs }),
  });
}

export function useResumeRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => api.post<StartRunOut>(`/runs/${runId}/resume`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.runs }),
  });
}

export function useCreateUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { email: string; name: string; role: string; password: string }) => api.post<UserOut>("/users", { body }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.users }),
  });
}

export function usePatchUser() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: string; role?: string; active?: boolean; name?: string; password?: string }) => api.patch<UserOut>(`/users/${id}`, { body }),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.users }),
  });
}
```

`web/src/features/papers/papersState.ts`:

```ts
import type { PaperParams } from "../../api/hooks";

export const PAGE_SIZE = 25;
const SORT = /^(title|year|score|criterion:[a-z0-9_]+)$/;
const DECISIONS = ["include", "exclude", "uncertain"];
const TIERS = ["jev", "llm", "rule"];

export type PapersView = { runId: string | null; paperId: string | null; stageId: string | null; params: PaperParams };

const number = (text: string | null, low: number, high: number) => {
  if (text === null || text === "") return undefined;
  const value = Number(text);
  return Number.isFinite(value) && value >= low && value <= high ? value : undefined;
};
const flag = (text: string | null) => (text === "true" ? true : text === "false" ? false : undefined);

export function parseView(search: URLSearchParams): PapersView {
  const sort = search.get("sort") ?? "title";
  const params: PaperParams = {
    page: Math.trunc(number(search.get("page"), 1, 1e6) ?? 1),
    page_size: PAGE_SIZE,
    sort: SORT.test(sort) ? sort : "title",
    direction: search.get("dir") === "desc" ? "desc" : "asc",
  };
  const decision = search.get("decision");
  if (decision && DECISIONS.includes(decision)) params.decision = decision;
  const tier = search.get("tier");
  if (tier && TIERS.includes(tier)) params.tier = tier;
  const escalated = flag(search.get("escalated"));
  if (escalated !== undefined) params.escalated = escalated;
  const inSr = flag(search.get("in_sr"));
  if (inSr !== undefined) params.in_sr = inSr;
  const pMin = number(search.get("pmin"), 0, 1);
  const pMax = number(search.get("pmax"), 0, 1);
  if (pMin !== undefined || pMax !== undefined) params.criterion = "topic_match";
  if (pMin !== undefined) params.p_min = pMin;
  if (pMax !== undefined) params.p_max = pMax;
  return { runId: search.get("run"), paperId: search.get("paper"), stageId: search.get("stage"), params };
}

type Changes = Partial<{
  run: string | null; page: number | null; sort: string | null; dir: "asc" | "desc" | null; decision: string | null; tier: string | null;
  escalated: boolean | null; in_sr: boolean | null; pmin: number | null; pmax: number | null; paper: string | null; stage: string | null;
}>;

/** Returns new search parameters. Any change other than `page`, `paper` or `stage` goes back to page 1; changing the run closes the panels. */
export function patchView(search: URLSearchParams, changes: Changes, resetPage = true): URLSearchParams {
  const next = new URLSearchParams(search);
  for (const [key, value] of Object.entries(changes)) {
    if (value === null || value === undefined) next.delete(key);
    else next.set(key, String(value));
  }
  if (changes.paper) next.delete("stage");
  if (changes.stage) next.delete("paper");
  if (changes.run !== undefined) {
    next.delete("paper");
    next.delete("stage");
  }
  if (resetPage && changes.page === undefined) next.delete("page");
  return next;
}
```

- [ ] **Step 5: Run and commit**

Run: `npm run typecheck && npm run lint && npm test`
Expected: green (`patchView` test: `"escalated=true&in_sr=true"` relies on `URLSearchParams` preserving insertion order, which it does).

```bash
cd .. && git add -A
git commit -m "Add query hooks, fixtures and the Papers URL state" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: The Papers page: pipeline strip, table, filters and paging

**Files:**
- Create: `web/src/features/papers/cells.tsx`, `PipelineStrip.tsx`, `PaperTable.tsx`, `FilterBar.tsx`, `web/src/pages/PapersPage.tsx`
- Modify: `web/src/App.tsx`, `web/src/pages/PlaceholderPages.tsx`, `web/src/styles.css`
- Test: `web/src/features/papers/cells.test.tsx`, `web/src/pages/PapersPage.test.tsx`

Rules the UI must keep: `null` cell → a dash with an accessible label; `{"missing": true}` → a hatched "missing" marker; only a `measured` stage looks green; the pipeline strip labels each stage with its status in words.

- [ ] **Step 1: Write the failing cell tests**

`web/src/features/papers/cells.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { lostRow, paperRow } from "../../test/fixtures";
import { DecisionCell, ExtractCellView, InSrCell, ReviewsCellView, ScoreCell, TopicMatchCell } from "./cells";

describe("tri-state cells", () => {
  it("shows a labelled dash when the stage does not apply", () => {
    render(<ExtractCellView cell={null} />);
    expect(screen.getByLabelText("not applicable")).toHaveTextContent("–");
  });

  it("shows a hatched marker, never a dash, when expected data is missing", () => {
    render(<ReviewsCellView cell={{ missing: true }} />);
    const marker = screen.getByText("missing");
    expect(marker).toHaveClass("missing");
    expect(screen.queryByLabelText("not applicable")).not.toBeInTheDocument();
  });

  it("shows the data when it is there", () => {
    render(<><ExtractCellView cell={{ claims: 5, quotes_verified: true }} /><ReviewsCellView cell={{ a: "include", b: "exclude", adjudicated: true, adjudicator: "uncertain" }} /></>);
    expect(screen.getByText("5 verified")).toBeInTheDocument();
    expect(screen.getByText(/inc \/ exc/)).toBeInTheDocument();
    expect(screen.getByText(/adj: unc/)).toBeInTheDocument();
  });
});

describe("screening cells", () => {
  it("shows the Jev probability with a Jev badge when Jev decided", () => {
    render(<TopicMatchCell screen={paperRow().screen} />);
    expect(screen.getByText("0.99")).toBeInTheDocument();
    expect(screen.getByText("Jev")).toBeInTheDocument();
  });

  it("marks an escalated paper and names the deciding tier", () => {
    render(<><TopicMatchCell screen={lostRow().screen} /><DecisionCell screen={lostRow().screen} /></>);
    expect(screen.getByText("0.06")).toBeInTheDocument();
    expect(screen.getByText("escalated")).toBeInTheDocument();
    expect(screen.getByText("drop")).toBeInTheDocument();
    expect(screen.getByText("LLM")).toBeInTheDocument();
  });

  it("shows a dash when there is no Jev score, and prefixes keys when there are several criteria", () => {
    const { rerender } = render(<TopicMatchCell screen={{ ...paperRow().screen, criteria: {} }} />);
    expect(screen.getByLabelText("not applicable")).toBeInTheDocument();
    rerender(<TopicMatchCell screen={{ ...paperRow().screen, criteria: { topic_match: 0.9, uses_dl: 0.4 } }} />);
    expect(screen.getByText("uses_dl 0.40")).toBeInTheDocument();
  });

  it("shows SR membership as words, and a dash when the run has no gold set", () => {
    const { rerender } = render(<InSrCell value={true} />);
    expect(screen.getByText("yes")).toBeInTheDocument();
    rerender(<InSrCell value={false} />);
    expect(screen.getByText("no")).toBeInTheDocument();
    rerender(<InSrCell value={null} />);
    expect(screen.getByLabelText("not applicable")).toBeInTheDocument();
    rerender(<ScoreCell rank={{ score: 81.6, position: 2 }} />);
    expect(screen.getByText("82")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/papers/cells.test.tsx`
Expected: FAIL, `Failed to resolve import "./cells"`.

- [ ] **Step 3: Implement `cells.tsx`**

```tsx
import type { PaperRow } from "../../api/types";

const VERDICT: Record<string, string> = { include: "inc", exclude: "exc", uncertain: "unc" };
const verdict = (value: string | null) => (value ? (VERDICT[value] ?? value) : "–");

export const NotApplicable = () => <span className="na" aria-label="not applicable">–</span>;
export const Missing = () => <span className="missing" title="Expected data is missing">missing</span>;

export function ExtractCellView({ cell }: { cell: PaperRow["extract"] }) {
  if (cell === null) return <NotApplicable />;
  if ("missing" in cell) return <Missing />;
  return <span>{cell.claims} {cell.quotes_verified ? "verified" : "unverified"}</span>;
}

export function ReviewsCellView({ cell }: { cell: PaperRow["reviews"] }) {
  if (cell === null) return <NotApplicable />;
  if ("missing" in cell) return <Missing />;
  return (
    <span>
      {verdict(cell.a)} / {verdict(cell.b)}
      {cell.adjudicated && <span className="adj"> adj: {verdict(cell.adjudicator)}</span>}
    </span>
  );
}

export function TopicMatchCell({ screen }: { screen: PaperRow["screen"] }) {
  const entries = Object.entries(screen.criteria);
  if (entries.length === 0) return <NotApplicable />;
  return (
    <span className="topic">
      {entries.map(([key, probability]) => (
        <span key={key}>
          {entries.length > 1 ? `${key} ` : ""}<strong>{probability.toFixed(2)}</strong>
        </span>
      ))}
      {screen.tier === "jev" && <span className="chip chip--ok">Jev</span>}
      {screen.jev_decision === "escalate" && <span className="chip chip--warn">escalated</span>}
    </span>
  );
}

const DECISION: Record<string, string> = { include: "keep", exclude: "drop", uncertain: "unsure" };
const TIER: Record<string, string> = { jev: "Jev", llm: "LLM", rule: "no abstract" };

export function DecisionCell({ screen }: { screen: PaperRow["screen"] }) {
  return (
    <span>
      <span className={`decision decision--${screen.decision}`}>{DECISION[screen.decision] ?? screen.decision}</span>{" "}
      <span className="chip">{TIER[screen.tier] ?? screen.tier}</span>
    </span>
  );
}

export const InSrCell = ({ value }: { value: boolean | null }) => (value === null ? <NotApplicable /> : <span>{value ? "yes" : "no"}</span>);
export const ScoreCell = ({ rank }: { rank: PaperRow["rank"] }) => (rank ? <span>{rank.score.toFixed(0)}</span> : <NotApplicable />);
export const FoundByCell = ({ value }: { value: string }) => <span>{value}</span>;
```

- [ ] **Step 4: Write the failing page tests**

`web/src/pages/PapersPage.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { lostRow, paperRow, runDetail, runOut, session, STAGES, RUN_ID } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { PapersPage } from "./PapersPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function Location() {
  const location = useLocation();
  return <output aria-label="location">{location.search}</output>;
}

const page = (items: unknown[], total = items.length, extra: Record<string, unknown> = {}) => ({ items, total, page: 1, page_size: 25, ...extra });

function setup(handlers: Parameters<typeof mockApi>[0] = {}, route = "/") {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session("member") },
    "GET /api/v1/runs": { body: [runOut({ id: "99999999-9999-4999-8999-999999999999", paper_count: 0, gold_set_name: null, kind: "research" }), runOut()] },
    "GET /api/v1/runs/:id": { body: runDetail() },
    "GET /api/v1/stages": { body: STAGES },
    "GET /api/v1/runs/:id/papers": { body: page([paperRow(), lostRow()], 2) },
    ...handlers,
  });
  renderWithProviders(
    <>
      <Routes><Route path="/" element={<PapersPage />} /></Routes>
      <Location />
    </>,
    { route },
  );
  return api;
}

describe("PapersPage", () => {
  it("opens on the first run that has papers and lists them with one column group per stage", async () => {
    const { calls } = setup();
    expect(await screen.findByText("Change in CT-Derived FFR Across the Lesion Improve the Diagnostic Performance")).toBeInTheDocument();
    expect(calls.some((c) => c.path === `/api/v1/runs/${RUN_ID}/papers`)).toBe(true);
    expect(screen.getByText(/151 screened/)).toBeInTheDocument();
    expect(screen.getByText(/112 kept/)).toBeInTheDocument();
  });

  it("labels every stage with its status in words and only measured stages look measured", async () => {
    setup();
    await screen.findByRole("table");
    const strip = screen.getAllByRole("button", { name: /^(Search|Screen|Extract|Reviewers|Rank)/ });
    const status = (label: RegExp) => strip.find((b) => label.test(b.textContent ?? ""))!;
    expect(status(/Search/)).toHaveAttribute("data-status", "measured");
    expect(status(/Screen/)).toHaveAttribute("data-status", "measured");
    expect(status(/Reviewers/)).toHaveAttribute("data-status", "caveat");
    expect(status(/Reviewers/)).toHaveTextContent("one model family");
    expect(status(/Rank/)).toHaveAttribute("data-status", "unmeasured");
    expect(status(/Rank/)).toHaveTextContent("not measured");
    expect(status(/Search/)).toHaveTextContent("recall 15/16");
  });

  it("shows not-applicable and missing differently, and the SR label in words", async () => {
    setup({ "GET /api/v1/runs/:id/papers": { body: page([paperRow({ extract: { missing: true } }), lostRow()], 2) } });
    const table = await screen.findByRole("table");
    expect(within(table).getByText("missing")).toBeInTheDocument();
    expect(within(table).getAllByLabelText("not applicable").length).toBeGreaterThan(0);
    expect(within(table).getAllByText("yes").length).toBe(2);
  });

  it("a filter chip changes the request, the URL and goes back to page 1", async () => {
    const { calls } = setup(
      { "GET /api/v1/runs/:id/papers": ({ url }) => ({ body: url.searchParams.get("decision") === "exclude" ? page([lostRow()], 1) : page([paperRow(), lostRow()], 60) }) },
      "/?page=2",
    );
    await screen.findByRole("table");
    await userEvent.click(screen.getByRole("button", { name: "Dropped" }));
    expect(await screen.findByRole("button", { name: "Dropped" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("location")).toHaveTextContent("decision=exclude");
    expect(screen.getByLabelText("location")).not.toHaveTextContent("page=");
    const last = calls.filter((c) => c.path.endsWith("/papers")).at(-1)!;
    expect(new URLSearchParams(last.search).get("decision")).toBe("exclude");
    expect(new URLSearchParams(last.search).get("page")).toBe("1");
    await userEvent.click(screen.getByRole("button", { name: "Dropped" })); // toggles off
    expect(screen.getByLabelText("location")).not.toHaveTextContent("decision=");
  });

  it("sorting by topic match toggles ascending and descending and sets aria-sort", async () => {
    const { calls } = setup();
    await screen.findByRole("table");
    const header = screen.getByRole("columnheader", { name: /Topic match/ });
    await userEvent.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "ascending");
    await userEvent.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "descending");
    const last = calls.filter((c) => c.path.endsWith("/papers")).at(-1)!;
    expect(new URLSearchParams(last.search).get("sort")).toBe("criterion:topic_match");
    expect(new URLSearchParams(last.search).get("direction")).toBe("desc");
  });

  it("pages forward and back and disables the buttons at the ends", async () => {
    const { calls } = setup({ "GET /api/v1/runs/:id/papers": ({ url }) => ({ body: page([paperRow()], 60, { page: Number(url.searchParams.get("page") ?? 1) }) }) });
    await screen.findByRole("table");
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    expect(new URLSearchParams(calls.filter((c) => c.path.endsWith("/papers")).at(-1)!.search).get("page")).toBe("2");
  });

  it("says so when nothing matches", async () => {
    setup({ "GET /api/v1/runs/:id/papers": { body: page([], 0) } });
    expect(await screen.findByText("No papers match these filters.")).toBeInTheDocument();
  });

  it("shows the request id when the table cannot be loaded", async () => {
    setup({ "GET /api/v1/runs/:id/papers": { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "req-7" } } });
    expect(await screen.findByRole("alert")).toHaveTextContent("req-7");
  });

  it("asks for a run when there is none", async () => {
    setup({ "GET /api/v1/runs": { body: [] } });
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run to verify failure**

Run: `npm test -- src/pages/PapersPage.test.tsx`
Expected: FAIL, `Failed to resolve import "./PapersPage"`.

- [ ] **Step 6: Implement the strip, the table and the filter bar**

`web/src/features/papers/PipelineStrip.tsx`:

```tsx
import type { StageOut } from "../../api/types";

export const STRIP = [
  { id: "paper", span: 1 }, { id: "search", span: 1 }, { id: "screen", span: 2 }, { id: "extract", span: 1 },
  { id: "reviewers", span: 1 }, { id: "rank", span: 1 }, { id: "sr", span: 1 },
] as const;

const STATUS_WORDS: Record<StageOut["status"], string> = { measured: "measured", caveat: "caveat", unmeasured: "not measured", input: "input" };

export function statusText(stage: StageOut) {
  return stage.status === "caveat" && stage.caveat ? stage.caveat : STATUS_WORDS[stage.status];
}

/** The first header row: the pipeline as column groups. Each stage button says what the stage is and whether it is measured. */
export function PipelineStrip({ stages, selectedId, onSelect }: { stages: StageOut[]; selectedId: string | null; onSelect: (id: string) => void }) {
  const byId = new Map(stages.map((stage) => [stage.id, stage]));
  return (
    <tr className="strip">
      {STRIP.map(({ id, span }) => {
        const stage = byId.get(id);
        if (!stage) {
          return <th key={id} colSpan={span} className="strip-plain">{id === "sr" ? "SR label" : ""}</th>;
        }
        return (
          <th key={id} colSpan={span} scope="colgroup" className={`strip-stage strip-stage--${stage.status}`}>
            <button type="button" className="stage" data-status={stage.status} aria-pressed={selectedId === id} onClick={() => onSelect(id)}>
              <span className="stage-title">{stage.title}</span>
              <span className="stage-status">{statusText(stage)}</span>
              {stage.headline && <span className="stage-headline">{stage.headline}</span>}
            </button>
          </th>
        );
      })}
    </tr>
  );
}
```

`web/src/features/papers/PaperTable.tsx`:

```tsx
import type { PaperRow, StageOut } from "../../api/types";
import { DecisionCell, ExtractCellView, FoundByCell, InSrCell, ReviewsCellView, ScoreCell, TopicMatchCell } from "./cells";
import { PipelineStrip } from "./PipelineStrip";

type Props = {
  rows: PaperRow[]; stages: StageOut[]; sort: string; direction: "asc" | "desc"; onSort: (sort: string) => void;
  selectedPaperId: string | null; onOpen: (paperId: string) => void; selectedStageId: string | null; onSelectStage: (id: string) => void;
};

function SortHeader({ label, sortKey, sort, direction, onSort }: { label: string; sortKey: string; sort: string; direction: string; onSort: (key: string) => void }) {
  const active = sort === sortKey;
  return (
    <th scope="col" aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="sort" onClick={() => onSort(sortKey)}>
        {label}{active ? (direction === "asc" ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );
}

export function PaperTable({ rows, stages, sort, direction, onSort, selectedPaperId, onOpen, selectedStageId, onSelectStage }: Props) {
  const sortProps = { sort, direction, onSort };
  return (
    <div className="table-scroll">
      <table className="papers">
        <thead>
          <PipelineStrip stages={stages} selectedId={selectedStageId} onSelect={onSelectStage} />
          <tr>
            <SortHeader label="Paper" sortKey="title" {...sortProps} />
            <th scope="col">Found by</th>
            <SortHeader label="Topic match" sortKey="criterion:topic_match" {...sortProps} />
            <th scope="col">Decision</th>
            <th scope="col">Claims</th>
            <th scope="col">Reviewers A / B</th>
            <SortHeader label="Score" sortKey="score" {...sortProps} />
            <th scope="col">In SR</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const selected = selectedPaperId === row.paper.id;
            return (
              <tr key={row.paper.id} className={`${row.screen.decision === "exclude" ? "dropped" : ""} ${selected ? "selected" : ""}`} aria-current={selected ? "true" : undefined} onClick={() => onOpen(row.paper.id)}>
                <td>
                  <button type="button" className="linklike" data-open-paper={row.paper.id} onClick={(event) => { event.stopPropagation(); onOpen(row.paper.id); }}>
                    {row.paper.title}
                  </button>
                  <span className="sub">{row.paper.year ?? ""} {row.paper.source_id}</span>
                </td>
                <td><FoundByCell value={row.found_by} /></td>
                <td><TopicMatchCell screen={row.screen} /></td>
                <td><DecisionCell screen={row.screen} /></td>
                <td><ExtractCellView cell={row.extract} /></td>
                <td><ReviewsCellView cell={row.reviews} /></td>
                <td><ScoreCell rank={row.rank} /></td>
                <td><InSrCell value={row.in_sr} /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

`web/src/features/papers/FilterBar.tsx`:

```tsx
import type { PapersView } from "./papersState";

type Change = Partial<{ decision: string | null; tier: string | null; escalated: boolean | null; in_sr: boolean | null; pmin: number | null; pmax: number | null }>;

const CHIPS: { label: string; active: (v: PapersView) => boolean; toggle: (v: PapersView) => Change }[] = [
  { label: "Included", active: (v) => v.params.decision === "include", toggle: (v) => ({ decision: v.params.decision === "include" ? null : "include" }) },
  { label: "Dropped", active: (v) => v.params.decision === "exclude", toggle: (v) => ({ decision: v.params.decision === "exclude" ? null : "exclude" }) },
  { label: "Unsure", active: (v) => v.params.decision === "uncertain", toggle: (v) => ({ decision: v.params.decision === "uncertain" ? null : "uncertain" }) },
  { label: "Decided by Jev", active: (v) => v.params.tier === "jev", toggle: (v) => ({ tier: v.params.tier === "jev" ? null : "jev" }) },
  { label: "Decided by the LLM", active: (v) => v.params.tier === "llm", toggle: (v) => ({ tier: v.params.tier === "llm" ? null : "llm" }) },
  { label: "Only escalated", active: (v) => v.params.escalated === true, toggle: (v) => ({ escalated: v.params.escalated === true ? null : true }) },
  { label: "In the SR", active: (v) => v.params.in_sr === true, toggle: (v) => ({ in_sr: v.params.in_sr === true ? null : true }) },
  { label: "Not in the SR", active: (v) => v.params.in_sr === false, toggle: (v) => ({ in_sr: v.params.in_sr === false ? null : false }) },
];

export function FilterBar({ view, onChange }: { view: PapersView; onChange: (change: Change) => void }) {
  const number = (text: string) => (text === "" ? null : Number(text));
  return (
    <div className="filters" role="group" aria-label="Filters">
      {CHIPS.map((chip) => (
        <button key={chip.label} type="button" aria-pressed={chip.active(view)} onClick={() => onChange(chip.toggle(view))}>{chip.label}</button>
      ))}
      <label>Topic match from <input type="number" min={0} max={1} step={0.05} value={view.params.p_min ?? ""} onChange={(e) => onChange({ pmin: number(e.target.value) })} /></label>
      <label>to <input type="number" min={0} max={1} step={0.05} value={view.params.p_max ?? ""} onChange={(e) => onChange({ pmax: number(e.target.value) })} /></label>
    </div>
  );
}
```

- [ ] **Step 7: Implement `web/src/pages/PapersPage.tsx`**

The drawer and stage panel arrive in the next task; this page reserves the side-panel slot (`{panel}`) and renders it when present.

```tsx
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { usePapers, useRun, useRuns, useStages } from "../api/hooks";
import { ErrorBoundary } from "../components/ErrorBoundary";
import { FilterBar } from "../features/papers/FilterBar";
import { PaperTable } from "../features/papers/PaperTable";
import { parseView, patchView } from "../features/papers/papersState";
import { PapersSidePanel } from "../features/papers/PapersSidePanel";

const errorText = (error: unknown) => (error instanceof ApiError ? `${error.message} (request ${error.requestId})` : "Could not reach the server.");

export function PapersPage() {
  const [search, setSearch] = useSearchParams();
  const view = parseView(search);
  const runs = useRuns();
  const runId = view.runId ?? runs.data?.find((run) => run.paper_count > 0)?.id ?? null;
  const run = useRun(runId);
  const papers = usePapers(runId, view.params);
  const stages = useStages();
  const change = (changes: Parameters<typeof patchView>[1], reset = true) => setSearch(patchView(search, changes, reset));

  if (runs.isLoading) return <p role="status">Loading…</p>;
  if (runs.isError) return <p role="alert">{errorText(runs.error)}</p>;
  if (!runId) return <section><h1>Papers</h1><p>No runs yet. Import a run or start one from the Runs page.</p></section>;

  const counts = run.data?.counts;
  const total = papers.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / view.params.page_size));
  const panelOpen = !!(view.paperId || view.stageId);

  return (
    <section className="papers-page">
      <h1>Papers</h1>
      <div className="toolbar">
        <label>
          Run
          <select value={runId} onChange={(e) => change({ run: e.target.value })}>
            {runs.data?.map((r) => (
              <option key={r.id} value={r.id}>{r.field_name} · {r.kind}{r.gold_set_name ? ` · ${r.gold_set_name}` : ""} · {r.paper_count} papers</option>
            ))}
          </select>
        </label>
        {counts && (
          <p className="summary">
            {counts.screened} screened · {counts.kept} kept · {counts.dropped} dropped · {counts.escalated} escalated to the LLM{counts.in_sr ? ` · ${counts.in_sr} in the SR` : ""}
          </p>
        )}
      </div>
      <FilterBar view={view} onChange={(changes) => change(changes)} />
      <div className={`papers-layout ${panelOpen ? "with-panel" : ""}`}>
        <div className="papers-main">
          {papers.isError ? (
            <p role="alert" className="form-error">{errorText(papers.error)}</p>
          ) : !papers.data ? (
            <p role="status">Loading papers…</p>
          ) : papers.data.items.length === 0 ? (
            <p>No papers match these filters.</p>
          ) : (
            <ErrorBoundary label="the paper table">
              <PaperTable
                rows={papers.data.items} stages={stages.data ?? []} sort={view.params.sort} direction={view.params.direction}
                onSort={(sort) => change({ sort, dir: view.params.sort === sort && view.params.direction === "asc" ? "desc" : "asc" })}
                selectedPaperId={view.paperId} onOpen={(paper) => change({ paper }, false)}
                selectedStageId={view.stageId} onSelectStage={(stage) => change({ stage: view.stageId === stage ? null : stage }, false)}
              />
            </ErrorBoundary>
          )}
          <nav className="pager" aria-label="Pages">
            <button type="button" disabled={view.params.page <= 1} onClick={() => change({ page: view.params.page - 1 }, false)}>Previous page</button>
            <span aria-live="polite">Page {view.params.page} of {pages}</span>
            <button type="button" disabled={view.params.page >= pages} onClick={() => change({ page: view.params.page + 1 }, false)}>Next page</button>
          </nav>
        </div>
        {panelOpen && (
          <ErrorBoundary label="the side panel">
            <PapersSidePanel runId={runId} paperId={view.paperId} stageId={view.stageId} stages={stages.data ?? []} onClose={() => change({ paper: null, stage: null }, false)} />
          </ErrorBoundary>
        )}
      </div>
    </section>
  );
}
```

Create a temporary `web/src/features/papers/PapersSidePanel.tsx` so the page compiles; the next task replaces its body:

```tsx
import type { StageOut } from "../../api/types";

type Props = { runId: string; paperId: string | null; stageId: string | null; stages: StageOut[]; onClose: () => void };

export function PapersSidePanel({ paperId, stageId }: Props) {
  return <aside aria-label="Details" data-paper={paperId ?? ""} data-stage={stageId ?? ""} />;
}
```

In `App.tsx` import `PapersPage` from `./pages/PapersPage` instead of the placeholder, and delete the `PapersPage` line from `PlaceholderPages.tsx`.

Append to `styles.css`:

```css
.toolbar { display: flex; gap: 16px; align-items: end; flex-wrap: wrap; margin-bottom: 8px; }
.toolbar label, .filters label { display: grid; gap: 2px; font-size: 12px; color: var(--muted); }
.summary { margin: 0; color: var(--muted); }
.filters { display: flex; gap: 6px; flex-wrap: wrap; align-items: end; margin-bottom: 12px; }
.filters input[type="number"] { width: 80px; }
.papers-layout { display: grid; gap: 12px; grid-template-columns: 1fr; }
.papers-layout.with-panel { grid-template-columns: minmax(0, 1fr) 380px; }
.table-scroll { overflow-x: auto; }
table.papers { border-collapse: collapse; width: 100%; }
table.papers th, table.papers td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
table.papers tr.dropped td { color: var(--muted); }
table.papers tr.selected td { background: var(--panel); }
.strip th { padding: 0; }
.strip-stage .stage { width: 100%; display: grid; gap: 1px; text-align: center; border: 0; border-bottom: 3px solid var(--line); border-radius: 6px 6px 0 0; padding: 6px 4px; }
.strip-stage--measured .stage { background: var(--ok-bg); color: var(--ok-fg); border-bottom-color: var(--ok-line); }
.strip-stage--caveat .stage, .strip-stage--unmeasured .stage { background: var(--warn-bg); color: var(--warn-fg); border-bottom-color: var(--warn-line); }
.strip-stage--input .stage { background: var(--neutral-bg); color: var(--neutral-fg); }
.stage[aria-pressed="true"] { outline: 2px solid var(--accent); }
.stage-title { font-weight: 600; }
.stage-status, .stage-headline { font-size: 11px; }
.linklike { border: 0; background: none; padding: 0; text-align: left; color: var(--accent); text-decoration: underline; cursor: pointer; }
.sub { display: block; color: var(--muted); font-size: 11px; }
.sort { border: 0; background: none; padding: 0; font-weight: 600; }
.chip { border: 1px solid var(--line); border-radius: 10px; padding: 0 6px; font-size: 11px; margin-left: 4px; }
.chip--ok { background: var(--ok-bg); color: var(--ok-fg); border-color: var(--ok-line); }
.chip--warn { background: var(--warn-bg); color: var(--warn-fg); border-color: var(--warn-line); }
.decision--exclude { color: var(--bad-fg); }
.na { color: var(--muted); }
.missing { padding: 0 6px; border: 1px dashed var(--warn-line); color: var(--warn-fg); border-radius: 4px; background: repeating-linear-gradient(45deg, transparent 0 4px, var(--warn-bg) 4px 8px); }
.pager { display: flex; gap: 12px; align-items: center; justify-content: center; margin-top: 12px; }
```

- [ ] **Step 8: Run and commit**

Run: `npm run typecheck && npm run lint && npm test && npm run build`
Expected: green.

```bash
cd .. && git add -A
git commit -m "Add the Papers page with the pipeline strip, tri-state cells, filters, sorting and paging" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: The paper drawer and the stage panel

**Files:**
- Modify: `web/src/features/papers/PapersSidePanel.tsx`, `web/src/pages/PapersPage.tsx`, `web/src/styles.css`
- Create: `web/src/features/papers/PaperDrawer.tsx`, `RawCalls.tsx`, `StagePanel.tsx`
- Test: `web/src/features/papers/drawer.test.tsx`

The drawer is the "why this paper?" story: a stage-by-stage timeline. It is an `aside` with a labelled heading that receives focus when it opens, closes on Escape or its button, and returns focus to the row's title button. Raw prompts and responses are for members and admins only and are loaded on demand.

- [ ] **Step 1: Write the failing tests**

`web/src/features/papers/drawer.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../../api/client";
import { drawerOut, lostRow, paperRow, runDetail, runOut, session, STAGES, RUN_ID } from "../../test/fixtures";
import { mockApi } from "../../test/mockApi";
import { renderWithProviders } from "../../test/render";
import { PapersPage } from "../../pages/PapersPage";
import { StagePanel } from "./StagePanel";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const LOST_ID = "55555555-5555-4555-8555-555555555555";

function Location() {
  return <output aria-label="location">{useLocation().search}</output>;
}

function setup(role: "viewer" | "member" = "member", extra: Parameters<typeof mockApi>[0] = {}, route = `/?run=${RUN_ID}&paper=${LOST_ID}`) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/runs": { body: [runOut()] },
    "GET /api/v1/runs/:id": { body: runDetail() },
    "GET /api/v1/stages": { body: STAGES },
    "GET /api/v1/runs/:id/papers": { body: { items: [paperRow(), lostRow()], total: 2, page: 1, page_size: 25 } },
    "GET /api/v1/runs/:id/papers/:id": { body: drawerOut() },
    ...extra,
  });
  renderWithProviders(<><Routes><Route path="/" element={<PapersPage />} /></Routes><Location /></>, { route });
  return api;
}

describe("paper drawer", () => {
  it("tells the story of the paper the screen lost, stage by stage", async () => {
    setup();
    const drawer = await screen.findByRole("complementary", { name: "Paper details" });
    expect(within(drawer).getByRole("heading", { name: /Change in CT-Derived FFR/ })).toHaveFocus();
    expect(within(drawer).getByText(/Found by direct lookup/)).toBeInTheDocument();
    expect(within(drawer).getByText("0.06")).toBeInTheDocument();
    expect(within(drawer).getByText(/not confident, so the LLM decided/i)).toBeInTheDocument();
    expect(within(drawer).getByText(/Auto-drop needs/)).toBeInTheDocument();
    expect(within(drawer).getByText(/70.8 and 67.4%/)).toBeInTheDocument();
    expect(within(drawer).getByText("Reviewer A")).toBeInTheDocument();
    expect(within(drawer).getByText("Adjudicator")).toBeInTheDocument();
    expect(within(drawer).getByText(/neither confirms nor rules out/)).toBeInTheDocument();
    expect(within(drawer).getByText(/Included by the systematic review/)).toBeInTheDocument();
  });

  it("shows the abstract on demand and never renders it as HTML", async () => {
    setup("viewer", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ paper: { ...drawerOut().paper, abstract: "<img src=x onerror=alert(1)> plain text" } }) } });
    await screen.findByRole("complementary", { name: "Paper details" });
    await userEvent.click(screen.getByRole("button", { name: "Abstract" }));
    expect(screen.getByText("<img src=x onerror=alert(1)> plain text")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("hides raw calls from viewers", async () => {
    setup("viewer");
    await screen.findByRole("complementary", { name: "Paper details" });
    expect(screen.queryByRole("button", { name: "Raw calls" })).not.toBeInTheDocument();
  });

  it("members can inspect the exact prompt and response of a call", async () => {
    const call = { key: "a".repeat(64), role: "screen", model: "anthropic:claude-sonnet-5", prompt_version: "m1.1", input: { payload: { topic: "t" } }, output: { decision: "exclude" } };
    const { calls } = setup("member", { [`GET /api/v1/runs/${RUN_ID}/calls/${"a".repeat(64)}`]: { body: call } });
    await screen.findByRole("complementary", { name: "Paper details" });
    await userEvent.click(screen.getByRole("button", { name: "Raw calls" }));
    await userEvent.click(screen.getByRole("button", { name: /Screen/ }));
    expect(await screen.findByText("anthropic:claude-sonnet-5")).toBeInTheDocument();
    expect(screen.getByText(/"decision": "exclude"/)).toBeInTheDocument();
    expect(calls.some((c) => c.path.endsWith(`/calls/${"a".repeat(64)}`))).toBe(true);
  });

  it("explains an unavailable audit trail instead of failing silently", async () => {
    setup("member", { [`GET /api/v1/runs/${RUN_ID}/calls/${"a".repeat(64)}`]: { status: 409, body: { code: "no_audit_trail", message: "This run's audit trail is not available", request_id: "r" } } });
    await screen.findByRole("complementary", { name: "Paper details" });
    await userEvent.click(screen.getByRole("button", { name: "Raw calls" }));
    await userEvent.click(screen.getByRole("button", { name: /Screen/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("audit trail is not available");
  });

  it("closes with Escape or the close button and returns focus to the paper's title", async () => {
    setup();
    await screen.findByRole("complementary", { name: "Paper details" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "Paper details" })).not.toBeInTheDocument());
    expect(screen.getByLabelText("location")).not.toHaveTextContent("paper=");
    await waitFor(() => expect(screen.getByRole("button", { name: /Change in CT-Derived FFR/ })).toHaveFocus());
  });

  it("clicking a paper title opens its drawer and puts it in the URL", async () => {
    setup("member", {}, `/?run=${RUN_ID}`);
    await userEvent.click(await screen.findByRole("button", { name: /Change in CT-Derived FFR/ }));
    expect(await screen.findByRole("complementary", { name: "Paper details" })).toBeInTheDocument();
    expect(screen.getByLabelText("location")).toHaveTextContent(`paper=${LOST_ID}`);
  });

  it("shows a research-run paper without an SR section", async () => {
    setup("member", { "GET /api/v1/runs/:id/papers/:id": { body: drawerOut({ in_sr: null, label_source: null, found_by: "query" }) } });
    const drawer = await screen.findByRole("complementary", { name: "Paper details" });
    expect(within(drawer).queryByText(/systematic review/)).not.toBeInTheDocument();
    expect(within(drawer).getByText(/Found by the search query/)).toBeInTheDocument();
  });
});

describe("stage panel", () => {
  it("shows what a stage does, its status and its limits, and links to the eval data", () => {
    mockApi({ "GET /api/v1/auth/me": { body: session("viewer") } });
    renderWithProviders(<StagePanel stage={STAGES.find((s) => s.id === "reviewers")!} onClose={() => undefined} />);
    expect(screen.getByRole("heading", { name: "Reviewers A and B" })).toBeInTheDocument();
    expect(screen.getByText("caveat: one model family")).toBeInTheDocument();
    expect(screen.getByText(/limits\./)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the eval report" })).toHaveAttribute("href", "/evals");
  });

  it("opens from a strip header and closes when the header is pressed again", async () => {
    setup("member", {}, `/?run=${RUN_ID}`);
    const strip = await screen.findByRole("button", { name: /^Screen/ });
    await userEvent.click(strip);
    expect(await screen.findByRole("complementary", { name: "About Screen" })).toBeInTheDocument();
    expect(screen.getByLabelText("location")).toHaveTextContent("stage=screen");
    await userEvent.click(screen.getByRole("button", { name: /^Screen/ }));
    await waitFor(() => expect(screen.queryByRole("complementary", { name: "About Screen" })).not.toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/features/papers/drawer.test.tsx`
Expected: FAIL (`Failed to resolve import "./StagePanel"`).

- [ ] **Step 3: Implement `StagePanel.tsx`**

```tsx
import { Link } from "react-router-dom";

import type { StageOut } from "../../api/types";
import { statusText } from "./PipelineStrip";

export function StagePanel({ stage, onClose, showPapersLink = false }: { stage: StageOut; onClose?: () => void; showPapersLink?: boolean }) {
  return (
    <aside aria-label={`About ${stage.title}`} className="side-panel">
      <div className="panel-head">
        <h2>{stage.title}</h2>
        {onClose && <button type="button" onClick={onClose} aria-label="Close stage details">×</button>}
      </div>
      <p><span className={`pill pill--${stage.status}`}>{stage.status === "caveat" ? `caveat: ${stage.caveat ?? "see limits"}` : statusText(stage)}</span> {stage.headline}</p>
      <h3>What it does</h3>
      <p>{stage.summary}</p>
      <h3>Known limits</h3>
      <p>{stage.limits}</p>
      <p className="links">
        {stage.data_link === "evals" && <Link to="/evals">Open the eval report</Link>}
        {stage.data_link === "papers" && showPapersLink && <Link to="/">See the screened papers</Link>}
      </p>
    </aside>
  );
}
```

- [ ] **Step 4: Implement `RawCalls.tsx`**

```tsx
import { useState } from "react";

import { ApiError } from "../../api/client";
import { useCall } from "../../api/hooks";
import type { DrawerOut } from "../../api/types";

type Item = { label: string; key: string };

export function callItems(drawer: DrawerOut): Item[] {
  const items: Item[] = [];
  const seen = new Set<string>();
  const add = (label: string, key: string | null | undefined) => {
    if (key && !seen.has(key)) {
      seen.add(key);
      items.push({ label, key });
    }
  };
  add(drawer.screening.tier === "jev" ? "Screen (Jev)" : "Screen (LLM)", drawer.screening.call_key);
  drawer.claims.forEach((claim) => add("Extract", claim.call_key));
  drawer.reviews.forEach((review) => add(review.role === "adjudicator" ? "Adjudicator" : `Reviewer ${review.role.toUpperCase()}`, review.call_key));
  return items;
}

function CallView({ runId, callKey }: { runId: string; callKey: string }) {
  const call = useCall(runId, callKey);
  if (call.isLoading) return <p role="status">Loading the call…</p>;
  if (call.isError) return <p role="alert" className="form-error">{call.error instanceof ApiError ? call.error.message : "Could not load the call."}</p>;
  const data = call.data!;
  return (
    <div className="call">
      <p><strong>{data.role}</strong> · <span>{data.model}</span> · prompt {data.prompt_version}</p>
      <details open><summary>Input</summary><pre>{JSON.stringify(data.input, null, 2)}</pre></details>
      <details open><summary>Output</summary><pre>{JSON.stringify(data.output, null, 2)}</pre></details>
    </div>
  );
}

export function RawCalls({ runId, drawer }: { runId: string; drawer: DrawerOut }) {
  const items = callItems(drawer);
  const [selected, setSelected] = useState<string | null>(null);
  if (items.length === 0) return <p>No model calls are recorded for this paper.</p>;
  return (
    <div>
      <div className="call-list" role="group" aria-label="Model calls">
        {items.map((item) => (
          <button key={item.key} type="button" aria-pressed={selected === item.key} onClick={() => setSelected(item.key)}>{item.label}</button>
        ))}
      </div>
      {selected && <CallView runId={runId} callKey={selected} />}
    </div>
  );
}
```

- [ ] **Step 5: Implement `PaperDrawer.tsx`**

```tsx
import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { usePaper } from "../../api/hooks";
import { hasRole, type DrawerOut, type ReviewOut } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { RawCalls } from "./RawCalls";

const ROLE_LABEL: Record<string, string> = { a: "Reviewer A", b: "Reviewer B", adjudicator: "Adjudicator" };
const JEV_MEANING: Record<string, string> = {
  include: "Jev was confident the paper matches.",
  exclude: "Jev was confident the paper does not match, so it was dropped without asking the LLM.",
  escalate: "Jev was not confident, so the LLM decided.",
};
const detailText = (review: ReviewOut, key: string) => (typeof review.detail[key] === "string" ? (review.detail[key] as string) : null);
const detailList = (review: ReviewOut, key: string) => (Array.isArray(review.detail[key]) ? (review.detail[key] as string[]) : []);

function Step({ title, tone, children }: { title: string; tone: "ok" | "warn" | "neutral"; children: React.ReactNode }) {
  return (
    <section className={`step step--${tone}`}>
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function Timeline({ drawer }: { drawer: DrawerOut }) {
  const { screening } = drawer;
  return (
    <div className="timeline">
      <Step title="Search" tone="ok">
        <p>{drawer.found_by === "lookup" ? "Found by direct lookup of the systematic review's reference, not by the search query." : "Found by the search query."}</p>
      </Step>
      <Step title="Screen" tone={screening.jev_decision === "escalate" ? "warn" : "ok"}>
        {screening.criteria.map((c) => (
          <p key={c.key}>{c.key}: <strong>{c.probability.toFixed(2)}</strong> <span className="sub">{c.jev_version}</span></p>
        ))}
        {screening.jev_decision && <p>{JEV_MEANING[screening.jev_decision]}</p>}
        {screening.jev_decision && <p className="sub">Auto-drop needs p ≤ 0.05 at the shipped default thresholds.</p>}
        {screening.llm_decision && <p>LLM screen: <strong>{screening.llm_decision}</strong></p>}
        <p className="sub">{screening.reason}</p>
      </Step>
      <Step title="Extract" tone="ok">
        {drawer.claims.length === 0 ? <p>No extraction for this paper in this run.</p> : drawer.claims.map((claim, index) => (
          <blockquote key={index}>“{claim.quote}”<footer>{claim.statement}</footer></blockquote>
        ))}
      </Step>
      <Step title="Reviewers" tone="warn">
        {drawer.reviews.length === 0 ? <p>No reviews for this paper in this run.</p> : drawer.reviews.map((review) => (
          <div key={review.role} className="review">
            <p><strong>{ROLE_LABEL[review.role] ?? review.role}</strong> <span className={`chip verdict--${review.verdict}`}>{review.verdict}</span> <span className="sub">relevance {review.relevance} · methods {review.methods} · support {review.support}</span></p>
            {detailText(review, "assessment") && <p>{detailText(review, "assessment")}</p>}
            {detailText(review, "reason") && <p>{detailText(review, "reason")}</p>}
            {(detailList(review, "strengths").length > 0 || detailList(review, "weaknesses").length > 0) && (
              <details><summary>Strengths and weaknesses</summary>
                <ul>{detailList(review, "strengths").map((s) => <li key={s}>+ {s}</li>)}{detailList(review, "weaknesses").map((w) => <li key={w}>− {w}</li>)}</ul>
              </details>
            )}
          </div>
        ))}
      </Step>
      <Step title="Rank" tone="neutral"><p>{drawer.rank ? `Rank ${drawer.rank.position} · score ${drawer.rank.score.toFixed(0)}` : "Not ranked."}</p></Step>
      {drawer.in_sr !== null && (
        <Step title="SR label" tone="ok">
          <p>{drawer.in_sr ? "Included by the systematic review" : "Not in the systematic review"}{drawer.label_source ? ` (${drawer.label_source})` : ""}.</p>
        </Step>
      )}
    </div>
  );
}

export function PaperDrawer({ runId, paperId, onClose }: { runId: string; paperId: string; onClose: () => void }) {
  const { user } = useAuth();
  const paper = usePaper(runId, paperId);
  const [section, setSection] = useState<"overview" | "abstract" | "calls">("overview");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    heading.current?.focus();
  }, [paper.data?.paper.id]);

  return (
    <aside aria-label="Paper details" className="side-panel" onKeyDown={(event) => event.key === "Escape" && onClose()}>
      <div className="panel-head">
        {paper.data ? <h2 ref={heading} tabIndex={-1}>{paper.data.paper.title}</h2> : <h2 ref={heading} tabIndex={-1}>Loading…</h2>}
        <button type="button" onClick={onClose} aria-label="Close paper details">×</button>
      </div>
      {paper.isError && <p role="alert" className="form-error">{paper.error instanceof ApiError ? `${paper.error.message} (request ${paper.error.requestId})` : "Could not load this paper."}</p>}
      {paper.data && (
        <>
          <p className="sub">{paper.data.paper.year ?? ""} · {paper.data.paper.source_id}{paper.data.paper.doi ? ` · ${paper.data.paper.doi}` : ""}</p>
          <div role="group" aria-label="Drawer sections" className="sections">
            <button type="button" aria-pressed={section === "overview"} onClick={() => setSection("overview")}>Overview</button>
            <button type="button" aria-pressed={section === "abstract"} onClick={() => setSection("abstract")}>Abstract</button>
            {hasRole(user, "member") && <button type="button" aria-pressed={section === "calls"} onClick={() => setSection("calls")}>Raw calls</button>}
          </div>
          {section === "overview" && <Timeline drawer={paper.data} />}
          {section === "abstract" && <p className="abstract">{paper.data.paper.abstract || "No abstract available."}</p>}
          {section === "calls" && <RawCalls runId={runId} drawer={paper.data} />}
        </>
      )}
    </aside>
  );
}
```

- [ ] **Step 6: Wire the side panel and return focus to the row**

Replace the body of `PapersSidePanel.tsx`:

```tsx
import type { StageOut } from "../../api/types";
import { PaperDrawer } from "./PaperDrawer";
import { StagePanel } from "./StagePanel";

type Props = { runId: string; paperId: string | null; stageId: string | null; stages: StageOut[]; onClose: () => void };

export function PapersSidePanel({ runId, paperId, stageId, stages, onClose }: Props) {
  if (paperId) return <PaperDrawer runId={runId} paperId={paperId} onClose={onClose} />;
  const stage = stages.find((s) => s.id === stageId);
  return stage ? <StagePanel stage={stage} onClose={onClose} /> : null;
}
```

In `PapersPage.tsx` change the close handler so focus returns to the title button of the paper that was open:

```tsx
  const close = () => {
    const open = view.paperId;
    change({ paper: null, stage: null }, false);
    if (open) requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-open-paper="${open}"]`)?.focus());
  };
```

and pass `onClose={close}` to `PapersSidePanel`. (`requestAnimationFrame` exists in jsdom, and `waitFor`/`findBy` in the drawer test wait for the next frame.)

Append to `styles.css`:

```css
.side-panel { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel); align-self: start; max-height: calc(100vh - 120px); overflow: auto; }
.panel-head { display: flex; justify-content: space-between; gap: 8px; align-items: start; }
.panel-head h2 { font-size: 16px; margin: 0; }
.side-panel h3 { font-size: 13px; margin: 12px 0 4px; }
.sections { display: flex; gap: 6px; margin: 8px 0; }
.step { border-left: 4px solid var(--line); padding: 2px 0 2px 10px; margin-bottom: 10px; }
.step--ok { border-left-color: var(--ok-line); }
.step--warn { border-left-color: var(--warn-line); }
.step h3 { margin: 0 0 2px; }
.step p { margin: 2px 0; }
blockquote { margin: 4px 0; padding-left: 8px; border-left: 2px solid var(--line); }
blockquote footer { color: var(--muted); font-size: 12px; }
.pill { border: 1px solid var(--line); border-radius: 10px; padding: 0 8px; font-size: 12px; }
.pill--measured { background: var(--ok-bg); color: var(--ok-fg); border-color: var(--ok-line); }
.pill--caveat, .pill--unmeasured { background: var(--warn-bg); color: var(--warn-fg); border-color: var(--warn-line); }
.call pre { max-height: 240px; overflow: auto; background: var(--bg); border: 1px solid var(--line); padding: 8px; font: 12px/1.4 var(--mono); }
.call-list { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.abstract { white-space: pre-wrap; }
@media (max-width: 900px) { .papers-layout.with-panel { grid-template-columns: 1fr; } }
```

- [ ] **Step 7: Run and commit**

Run: `npm run typecheck && npm run lint && npm test && npm run build`
Expected: green.

```bash
cd .. && git add -A
git commit -m "Add the paper drawer, raw calls and the stage panel" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 7: Backend: store the holdout sweep so the Evals grid can flag risky pairs

**Files:**
- Modify: `src/research_agent/eval/report.py`
- Test: `tests/test_eval_report.py`

The threshold grid must colour a pair red when it would lose an SR-included paper on the holdout set. `build_report` computes the holdout sweep (`holdout_rows`) but only stores the single recommended pair's holdout result, and stores nothing when no pair is admissible. Store the sweep rows in a new top-level key `holdout_sweep`. Nothing else changes; the importer stores `metrics.json` whole, so the web app receives the key without any importer change.

- [ ] **Step 1: Write the failing tests (append to `tests/test_eval_report.py`)**

```python
def test_report_keeps_the_holdout_sweep_so_pairs_can_be_judged_on_both_sets(tmp_path):
    main = screened_run(tmp_path / "a")
    report = build_report(main, holdout_dir=holdout_run(tmp_path / "b"))
    stored = report["holdout_sweep"]
    assert stored["gold"] == "other" and stored["n"] == 12
    assert {(r["min_confidence"], r["exclude_min_confidence"]) for r in stored["rows"]} == {
        (r["min_confidence"], r["exclude_min_confidence"]) for r in report["sweep"]
    }
    # The vetoed pair from the test above is visible as losing a paper on the holdout.
    vetoed = next(r for r in stored["rows"] if (r["min_confidence"], r["exclude_min_confidence"]) == (0.8, 0.95))
    assert vetoed["lost_vs_llm"] >= 1 and vetoed["lost_ids"]


def test_holdout_sweep_is_null_without_a_holdout_run(run_dir):
    assert build_report(run_dir)["holdout_sweep"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_report.py -k holdout_sweep -v`
Expected: FAIL with `KeyError: 'holdout_sweep'`.

- [ ] **Step 3: Implement**

In `build_report`, initialise the value next to the other holdout variables, fill it where `holdout_rows` is computed, and return it:

```python
    other_records = holdout_rows = holdout_sweep = None
```

```python
        holdout_rows = sweep(other_records)
        holdout_sweep = {"gold": other.name, "n": len(other_records), "rows": holdout_rows}
```

and in the returned dict, after `"holdout": holdout,`:

```python
        "holdout_sweep": holdout_sweep,
```

- [ ] **Step 4: Run and commit**

Run: `pytest -q && ruff check .`
Expected: all tests pass (the plan 1 and 2 web tests included), lint clean.

```bash
git add -A
git commit -m "Store the holdout threshold sweep in the eval metrics" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: Runs page: list, start a run, follow it, resume a failed one

**Files:**
- Create: `web/src/features/runs/RunList.tsx`, `StartRunForm.tsx`, `JobProgress.tsx`, `web/src/pages/RunsPage.tsx`
- Modify: `web/src/App.tsx`, `web/src/pages/PlaceholderPages.tsx`, `web/src/test/fixtures.ts`, `web/src/styles.css`
- Test: `web/src/pages/RunsPage.test.tsx`

Behaviour: everybody sees the list; members and admins also get the "Start a run" form. A run that failed shows a red banner with the sanitized reason the worker stored (it already names the failed stage) and a Resume button. A run started here is followed by polling its job every 2 seconds until it is done or failed; after a reload only the list status is shown (the API has no "job of this run" lookup by design).

- [ ] **Step 1: Add job fixtures (append to `web/src/test/fixtures.ts`)**

```ts
import type { JobOut } from "../api/types";

export const JOB_ID = "66666666-6666-4666-8666-666666666666";

export const jobOut = (over: Partial<JobOut> = {}): JobOut => ({
  id: JOB_ID, kind: "research", status: "queued", progress: {}, error: null, run_id: RUN_ID, attempts: 0, created_at: "2026-09-26T10:00:00Z", ...over,
});

export const fieldOut = () => ({
  id: FIELD_ID, name: "ML CT-FFR", topic: "deep learning CT-FFR",
  criteria: [{ id: "77777777-7777-4777-8777-777777777777", key: "topic_match", question: "The paper's central subject is the topic.", version: 1, position: 0 }],
});
```

- [ ] **Step 2: Write the failing tests**

`web/src/pages/RunsPage.test.tsx`:

```tsx
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { fieldOut, FIELD_ID, JOB_ID, jobOut, RUN_ID, runOut, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { RunsPage } from "./RunsPage";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const FAILED = runOut({ id: "88888888-8888-4888-8888-888888888888", kind: "research", status: "failed", gold_set_name: null, paper_count: 0, error: "failed at stage 'screen': ValidationError: Etapa nu s-a încheiat." });

function setup(role: "viewer" | "member" = "member", extra: Parameters<typeof mockApi>[0] = {}) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session(role) },
    "GET /api/v1/runs": { body: [FAILED, runOut()] },
    "GET /api/v1/fields": { body: [fieldOut()] },
    ...extra,
  });
  renderWithProviders(<RunsPage />);
  return api;
}

describe("RunsPage list", () => {
  it("lists runs with a status in words", async () => {
    setup("viewer");
    const table = await screen.findByRole("table");
    expect(within(table).getByText("failed")).toBeInTheDocument();
    expect(within(table).getByText("done")).toBeInTheDocument();
    expect(within(table).getByText("mlffrct-2024")).toBeInTheDocument();
    expect(within(table).getAllByRole("link", { name: /See papers/ })[1]).toHaveAttribute("href", `/?run=${RUN_ID}`);
  });

  it("viewers do not get the start form", async () => {
    setup("viewer");
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: "Start run" })).not.toBeInTheDocument();
  });

  it("a failed run shows why and offers Resume to members only", async () => {
    setup("member");
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("failed at stage 'screen'");
    expect(within(banner).getByRole("button", { name: "Resume" })).toBeInTheDocument();
  });

  it("viewers see the reason but no Resume button", async () => {
    setup("viewer");
    expect(await screen.findByRole("alert")).toHaveTextContent("failed at stage 'screen'");
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
  });

  it("says so when there are no runs", async () => {
    setup("viewer", { "GET /api/v1/runs": { body: [] } });
    expect(await screen.findByText("No runs yet.")).toBeInTheDocument();
  });
});

describe("starting and following a run", () => {
  it("posts the field and the cap with an idempotency key and shows the job", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/runs": { status: 202, body: { job: jobOut(), run_id: RUN_ID } },
      [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "running", progress: { status: "running", stages: { plan: "completed", search: "running" } } }) },
    });
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.clear(screen.getByLabelText("Papers to screen"));
    await userEvent.type(screen.getByLabelText("Papers to screen"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    const post = calls.find((c) => c.method === "POST" && c.path === "/api/v1/runs")!;
    expect(post.body).toEqual({ field_id: FIELD_ID, max_papers: 5, mode: "live" });
    expect(post.headers.get("Idempotency-Key")).toBeTruthy();
    const progress = await screen.findByRole("status", { name: "Run progress" });
    await waitFor(() => expect(progress).toHaveTextContent("running"));
    expect(progress).toHaveTextContent("plan: completed");
    expect(progress).toHaveTextContent("search: running");
  });

  it("refreshes the run list when the job finishes", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/runs": { status: 202, body: { job: jobOut(), run_id: RUN_ID } },
      [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "done" }) },
    });
    await screen.findByRole("table");
    const before = calls.filter((c) => c.method === "GET" && c.path === "/api/v1/runs").length;
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && c.path === "/api/v1/runs").length).toBeGreaterThan(before + 1));
  });

  it("the demo box switches the mode", async () => {
    const { calls } = setup("member", { "POST /api/v1/runs": { status: 202, body: { job: jobOut({ status: "done" }), run_id: RUN_ID } }, [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "done" }) } });
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.click(screen.getByLabelText(/Demo mode/));
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/api/v1/runs")?.body).toMatchObject({ mode: "demo" }));
  });

  it("refuses a cap outside 1 to 12 before calling the server", async () => {
    const { calls } = setup();
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.clear(screen.getByLabelText("Papers to screen"));
    await userEvent.type(screen.getByLabelText("Papers to screen"), "13");
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText("Choose between 1 and 12 papers.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the server's reason when it refuses (too many active runs)", async () => {
    setup("member", { "POST /api/v1/runs": { status: 429, body: { code: "too_many_active_runs", message: "You already have the maximum number of active runs", request_id: "r-1" } } });
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    expect(await screen.findByText(/maximum number of active runs/)).toBeInTheDocument();
  });

  it("a failed job shows its stored error", async () => {
    setup("member", {
      "POST /api/v1/runs": { status: 202, body: { job: jobOut(), run_id: RUN_ID } },
      [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "failed", error: "failed at stage 'search': HTTPError: 503" }) },
    });
    await screen.findByRole("table");
    await userEvent.selectOptions(screen.getByLabelText("Field"), FIELD_ID);
    await userEvent.click(screen.getByRole("button", { name: "Start run" }));
    const progress = await screen.findByRole("status", { name: "Run progress" });
    await waitFor(() => expect(progress).toHaveTextContent("failed at stage 'search'"));
  });
});

describe("resume", () => {
  it("resumes the failed run and follows the new job", async () => {
    const { calls } = setup("member", {
      "POST /api/v1/runs/:id/resume": { status: 202, body: { job: jobOut(), run_id: FAILED.id } },
      [`GET /api/v1/jobs/${JOB_ID}`]: { body: jobOut({ status: "running" }) },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));
    await screen.findByRole("status", { name: "Run progress" });
    expect(calls.some((c) => c.method === "POST" && c.path === `/api/v1/runs/${FAILED.id}/resume`)).toBe(true);
  });

  it("explains a refused resume", async () => {
    setup("member", { "POST /api/v1/runs/:id/resume": { status: 409, body: { code: "conflict", message: "Only a failed research run can be resumed", request_id: "r-2" } } });
    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));
    expect(await screen.findByText(/Only a failed research run can be resumed/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to verify failure**

Run: `npm test -- src/pages/RunsPage.test.tsx`
Expected: FAIL, `Failed to resolve import "./RunsPage"`.

- [ ] **Step 4: Implement the pieces**

`web/src/features/runs/JobProgress.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { keys, useJob } from "../../api/hooks";

const WORDS: Record<string, string> = { queued: "queued", running: "running", done: "done", failed: "failed" };

/** Follows one job. `useJob` polls every 2 seconds until the job is done or failed. */
export function JobProgress({ jobId }: { jobId: string }) {
  const job = useJob(jobId);
  const client = useQueryClient();
  const finished = job.data?.status === "done" || job.data?.status === "failed";
  // The run list was loaded while the run was queued; refresh it once the run has finished.
  useEffect(() => {
    if (finished) void client.invalidateQueries({ queryKey: keys.runs });
  }, [finished, client]);
  if (job.isError) return <p role="alert" className="form-error">Could not read the job status.</p>;
  const stages = Object.entries((job.data?.progress as { stages?: Record<string, string> } | undefined)?.stages ?? {});
  return (
    // One stable wrapper, so the element a screen reader is on does not get replaced when data arrives.
    <div role="status" aria-label="Run progress" className="job">
      {!job.data ? (
        <p>Waiting for the worker…</p>
      ) : (
        <>
          <p><strong>{WORDS[job.data.status] ?? job.data.status}</strong>{job.data.attempts > 1 ? ` · attempt ${job.data.attempts}` : ""}</p>
          {stages.length > 0 && <ul>{stages.map(([stage, state]) => <li key={stage}>{stage}: {state}</li>)}</ul>}
          {job.data.error && <p className="form-error">{job.data.error}</p>}
        </>
      )}
    </div>
  );
}
```

`web/src/features/runs/StartRunForm.tsx`:

```tsx
import { useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useFields, useStartRun } from "../../api/hooks";

export const MAX_PAPERS = 12;

export function StartRunForm({ onStarted }: { onStarted: (jobId: string) => void }) {
  const fields = useFields();
  const start = useStartRun();
  const [fieldId, setFieldId] = useState("");
  const [papers, setPapers] = useState("5");
  const [demo, setDemo] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const count = Number(papers);
    if (!fieldId) return setProblem("Choose a field.");
    if (!Number.isInteger(count) || count < 1 || count > MAX_PAPERS) return setProblem(`Choose between 1 and ${MAX_PAPERS} papers.`);
    setProblem(null);
    try {
      const started = await start.mutateAsync({ field_id: fieldId, max_papers: count, mode: demo ? "demo" : "live" });
      onStarted(started.job.id);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };

  return (
    <form onSubmit={submit} className="start-run" aria-label="Start a run">
      <label>Field
        <select value={fieldId} onChange={(e) => setFieldId(e.target.value)}>
          <option value="">Choose…</option>
          {fields.data?.map((field) => <option key={field.id} value={field.id}>{field.name}</option>)}
        </select>
      </label>
      <label>Papers to screen
        <input inputMode="numeric" value={papers} onChange={(e) => setPapers(e.target.value)} />
      </label>
      <label className="check"><input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> Demo mode (no model calls)</label>
      <button type="submit" disabled={start.isPending}>Start run</button>
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </form>
  );
}
```

`web/src/features/runs/RunList.tsx`:

```tsx
import { Link } from "react-router-dom";

import type { RunOut } from "../../api/types";

export function RunList({ runs }: { runs: RunOut[] }) {
  if (runs.length === 0) return <p>No runs yet.</p>;
  return (
    <table className="runs">
      <thead>
        <tr><th scope="col">Field</th><th scope="col">Kind</th><th scope="col">Status</th><th scope="col">Gold set</th><th scope="col">Papers</th><th scope="col">Created</th><th scope="col"><span className="sr-only">Actions</span></th></tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr key={run.id}>
            <td>{run.field_name}</td>
            <td>{run.kind}</td>
            <td><span className={`pill pill--run-${run.status}`}>{run.status}</span></td>
            <td>{run.gold_set_name ?? "–"}</td>
            <td>{run.paper_count}</td>
            <td>{new Date(run.created_at).toLocaleString()}</td>
            <td><Link to={`/?run=${run.id}`}>See papers<span className="sr-only"> for {run.field_name}, {run.kind}</span></Link></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

`web/src/pages/RunsPage.tsx`:

```tsx
import { useState } from "react";

import { ApiError } from "../api/client";
import { useResumeRun, useRuns } from "../api/hooks";
import { hasRole } from "../api/types";
import { useAuth } from "../auth/AuthProvider";
import { JobProgress } from "../features/runs/JobProgress";
import { RunList } from "../features/runs/RunList";
import { StartRunForm } from "../features/runs/StartRunForm";

export function RunsPage() {
  const { user } = useAuth();
  const runs = useRuns();
  const resume = useResumeRun();
  const [jobId, setJobId] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const canRun = hasRole(user, "member");

  const doResume = async (runId: string) => {
    setProblem(null);
    try {
      setJobId((await resume.mutateAsync(runId)).job.id);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };

  if (runs.isLoading) return <p role="status">Loading…</p>;
  if (runs.isError) return <p role="alert">Could not load the runs.</p>;
  const failed = runs.data?.filter((run) => run.status === "failed") ?? [];

  return (
    <section>
      <h1>Runs</h1>
      {canRun && <StartRunForm onStarted={setJobId} />}
      {jobId && <JobProgress jobId={jobId} />}
      {failed.map((run) => (
        <div key={run.id} role="alert" className="banner banner--bad">
          <p><strong>{run.field_name} · {run.kind} failed.</strong> {run.error ?? "No details were stored."}</p>
          {canRun && run.kind === "research" && <button type="button" onClick={() => doResume(run.id)} disabled={resume.isPending}>Resume</button>}
        </div>
      ))}
      {problem && <p role="alert" className="form-error">{problem}</p>}
      <RunList runs={runs.data ?? []} />
    </section>
  );
}
```

(The failed-run banner uses `role="alert"`; the test that expects a single `alert` in the viewer case relies on there being exactly one failed run in the fixture.)

In `App.tsx` import `RunsPage` from `./pages/RunsPage`; remove its line from `PlaceholderPages.tsx`. Append to `styles.css` (also add the `.sr-only` utility if Task 3 did not):

```css
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
.start-run { display: flex; gap: 12px; align-items: end; flex-wrap: wrap; margin: 12px 0; }
.start-run label { display: grid; gap: 2px; font-size: 12px; color: var(--muted); }
.start-run .check { display: flex; gap: 6px; align-items: center; }
.banner { border: 1px solid var(--line); border-left-width: 4px; border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
.banner--bad { border-left-color: var(--bad-line); background: var(--bad-bg); color: var(--bad-fg); }
.job { border: 1px solid var(--line); border-radius: 6px; padding: 8px 12px; margin: 8px 0; }
table.runs { border-collapse: collapse; width: 100%; }
table.runs th, table.runs td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); }
.pill--run-done { background: var(--ok-bg); color: var(--ok-fg); border-color: var(--ok-line); }
.pill--run-failed { background: var(--bad-bg); color: var(--bad-fg); border-color: var(--bad-line); }
.pill--run-running, .pill--run-queued { background: var(--warn-bg); color: var(--warn-fg); border-color: var(--warn-line); }
```

- [ ] **Step 5: Run and commit**

Run: `npm run typecheck && npm run lint && npm test && npm run build`
Expected: green.

```bash
cd .. && git add -A
git commit -m "Add the Runs page: list, start, follow a job and resume a failed run" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Evals page: summary cards, recall intervals, the threshold grid

**Files:**
- Create: `web/src/features/evals/metrics.ts`, `RecallRows.tsx`, `ThresholdGrid.tsx`, `web/src/pages/EvalsPage.tsx`
- Modify: `web/src/App.tsx`, `web/src/pages/PlaceholderPages.tsx`, `web/src/test/fixtures.ts`, `web/src/styles.css`
- Test: `web/src/features/evals/metrics.test.ts`, `web/src/pages/EvalsPage.test.tsx`

`EvalDetailOut.metrics` is an untyped JSON object, so the page reads it through one parser (`parseEval`) that turns it into a typed view and drops what it cannot trust. Rules the page must keep: the numbers shown are exactly the numbers in `metrics.json`; recall is shown as `k/n` with its interval, never a bare percentage; a `null` rate says why; the shipped default pair is outlined, the recommended pair starred, and a pair that loses an SR-included paper on the holdout is red **and** marked with words, never colour alone.

- [ ] **Step 1: Add the eval fixtures (append to `web/src/test/fixtures.ts`)**

```ts
import type { EvalDetailOut, EvalSummaryOut } from "../api/types";

export const EVAL_ID = "99999999-9999-4999-8999-999999999999";
export const rate = (k: number, n: number, ci: [number, number]) => ({ k, n, value: n ? k / n : null, ci, reason: null });
const row = (inc: number, exc: number, saved: number, lost: number, lostIds: string[] = []) => ({
  min_confidence: inc, exclude_min_confidence: exc, recall: rate(16 - lost, 16, [0.72, 0.99]), missed: lost, lost_vs_llm: lost, lost_ids: lostIds,
  calls_saved: saved, auto_include: 10, auto_exclude: 20, escalated: 151 - saved, kept: 100, kept_negatives: 84,
});

export const evalMetrics = () => ({
  gold: { name: "mlffrct-2024", citation: "Zhao et al. 2024", topic: "ML CT-FFR", query: "q", sha256: "f".repeat(64) },
  counts: { candidates: 151, screened: 151, positives_total: 16, positives_resolved: 16, positives_screened: 16 },
  retrieval_recall: rate(15, 16, [0.72, 0.99]),
  default_thresholds: { min_confidence: 0.6, exclude_min_confidence: 0.9 },
  strategies: {
    llm_only: { recall: rate(15, 16, [0.72, 0.99]), calls_saved: 0, escalated: 151, kept: 112, kept_negatives: 97 },
    jev_only: { recall: rate(14, 16, [0.64, 0.97]), calls_saved: 151, escalated: 82, kept: 100, kept_negatives: 85 },
    cascade: { recall: rate(15, 16, [0.72, 0.99]), calls_saved: 69, escalated: 82, kept: 112, kept_negatives: 97 },
  },
  sweep: [row(0.6, 0.9, 69, 0), row(0.1, 0.7, 74, 0), row(0.1, 0.5, 80, 1, ["MED:1"]), row(0.6, 0.99, 40, 0)],
  holdout_sweep: { gold: "aiffr-slr-2023", n: 25, rows: [row(0.6, 0.9, 12, 0), row(0.1, 0.7, 14, 0), row(0.1, 0.5, 16, 1, ["MED:9"]), row(0.6, 0.99, 8, 1, ["MED:8"])] },
  recommended: { min_confidence: 0.1, exclude_min_confidence: 0.7, calls_saved: 74 },
  rejected_on_holdout: { thresholds: { min_confidence: 0.1, exclude_min_confidence: 0.5 }, lost: [{ id: "MED:9", title: "A holdout paper the pair would lose" }] },
  holdout: { gold: "aiffr-slr-2023", n: 25, recall: rate(4, 5, [0.38, 0.96]), thresholds: { min_confidence: 0.1, exclude_min_confidence: 0.7 }, calls_saved: 14, lost_vs_llm: [], missed: [] },
  agreement: {
    n: 36, verdict: { kappa: 0.945, agreement: 0.972, reason: null }, scores: {}, adjudication_rate: rate(1, 36, [0.005, 0.14]), same_family: true,
  },
  warnings: ["The main-set-only pick include>=0.1/exclude>=0.5 loses 1 SR-included paper on the holdout that llm_only keeps: MED:9 'A holdout paper the pair would lose'. Rejected."],
});

export const evalSummary = (over: Partial<EvalSummaryOut> = {}): EvalSummaryOut => ({
  id: EVAL_ID, gold_set: { id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", name: "mlffrct-2024", citation: "Zhao et al. 2024" }, run_id: RUN_ID, created_at: "2026-09-26T09:00:00Z",
  headline: { retrieval_recall: { k: 15, n: 16 }, cascade_recall: { k: 15, n: 16 }, recommended: { min_confidence: 0.1, exclude_min_confidence: 0.7 }, kappa: 0.945, same_family: true, screened: 151 }, ...over,
});

export const evalDetail = (metrics: Record<string, unknown> = evalMetrics()): EvalDetailOut => ({
  id: EVAL_ID, gold_set: evalSummary().gold_set, run_id: RUN_ID, created_at: "2026-09-26T09:00:00Z", metrics, agreement: (metrics.agreement as Record<string, unknown>) ?? null,
});
```

- [ ] **Step 2: Write the failing parser tests**

`web/src/features/evals/metrics.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { evalMetrics } from "../../test/fixtures";
import { formatRate, parseEval, rowFor } from "./metrics";

describe("parseEval", () => {
  it("reads the parts of metrics.json the page shows", () => {
    const view = parseEval(evalMetrics());
    expect(view.gold.name).toBe("mlffrct-2024");
    expect(view.retrievalRecall).toMatchObject({ k: 15, n: 16 });
    expect(view.strategies.map((s) => s.name)).toEqual(["llm_only", "jev_only", "cascade"]);
    expect(view.defaultPair).toEqual({ include: 0.6, exclude: 0.9 });
    expect(view.recommended).toEqual({ include: 0.1, exclude: 0.7 });
    expect(view.holdout?.gold).toBe("aiffr-slr-2023");
    expect(view.rejected?.pair).toEqual({ include: 0.1, exclude: 0.5 });
    expect(view.agreement?.kappa).toBe(0.945);
    expect(view.agreement?.sameFamily).toBe(true);
    expect(view.warnings).toHaveLength(1);
  });

  it("copes with a report that has no holdout, no agreement and no recommendation", () => {
    const view = parseEval({ ...evalMetrics(), holdout_sweep: null, holdout: null, rejected_on_holdout: null, agreement: null, recommended: null });
    expect(view.holdout).toBeNull();
    expect(view.rejected).toBeNull();
    expect(view.agreement).toBeNull();
    expect(view.recommended).toBeNull();
  });

  it("does not crash on an unexpected shape, it just shows less", () => {
    const view = parseEval({});
    expect(view.strategies).toEqual([]);
    expect(view.sweep).toEqual([]);
    expect(view.retrievalRecall).toBeNull();
  });
});

describe("formatRate", () => {
  it("shows k/n with the interval, and the reason when it is undefined", () => {
    expect(formatRate({ k: 15, n: 16, value: 15 / 16, ci: [0.72, 0.99], reason: null })).toBe("15/16 (95% CI 0.72–0.99)");
    expect(formatRate({ k: 0, n: 0, value: null, ci: null, reason: "zero denominator" })).toBe("n/a (zero denominator)");
    expect(formatRate(null)).toBe("n/a");
  });
});

describe("rowFor", () => {
  it("finds the sweep row for a pair, or undefined", () => {
    const rows = parseEval(evalMetrics()).sweep;
    expect(rowFor(rows, { include: 0.6, exclude: 0.9 })?.callsSaved).toBe(69);
    expect(rowFor(rows, { include: 0.9, exclude: 0.5 })).toBeUndefined();
  });
});
```

- [ ] **Step 3: Run to verify failure**

Run: `npm test -- src/features/evals/metrics.test.ts`
Expected: FAIL, `Failed to resolve import "./metrics"`.

- [ ] **Step 4: Implement `web/src/features/evals/metrics.ts`**

```ts
export type Rate = { k: number; n: number; value: number | null; ci: [number, number] | null; reason: string | null };
export type Pair = { include: number; exclude: number };
export type SweepRow = { pair: Pair; recall: Rate | null; missed: number; lost: number; lostIds: string[]; callsSaved: number; escalated: number };
export type Strategy = { name: "llm_only" | "jev_only" | "cascade"; recall: Rate | null; callsSaved: number; escalated: number; kept: number; keptNegatives: number };
export type EvalView = {
  gold: { name: string; citation: string };
  screened: number | null;
  retrievalRecall: Rate | null;
  defaultPair: Pair | null;
  strategies: Strategy[];
  sweep: SweepRow[];
  holdout: { gold: string; n: number; recall: Rate | null; pair: Pair | null; callsSaved: number | null } | null;
  holdoutSweep: { gold: string; n: number; rows: SweepRow[] } | null;
  recommended: Pair | null;
  rejected: { pair: Pair; lost: { id: string; title: string }[] } | null;
  agreement: { n: number; kappa: number | null; agreement: number | null; reason: string | null; sameFamily: boolean | null; adjudicated: Rate | null } | null;
  warnings: string[];
};

type Json = Record<string, unknown>;
const obj = (value: unknown): Json | null => (value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : null);
const num = (value: unknown): number | null => (typeof value === "number" && Number.isFinite(value) ? value : null);
const str = (value: unknown, fallback = ""): string => (typeof value === "string" ? value : fallback);

export function toRate(value: unknown): Rate | null {
  const r = obj(value);
  if (!r || num(r.k) === null || num(r.n) === null) return null;
  const ci = Array.isArray(r.ci) && r.ci.length === 2 && r.ci.every((x) => num(x) !== null) ? ([r.ci[0], r.ci[1]] as [number, number]) : null;
  return { k: r.k as number, n: r.n as number, value: num(r.value), ci, reason: typeof r.reason === "string" ? r.reason : null };
}

const toPair = (value: unknown): Pair | null => {
  const p = obj(value);
  const include = num(p?.min_confidence);
  const exclude = num(p?.exclude_min_confidence);
  return include === null || exclude === null ? null : { include, exclude };
};

function toRows(value: unknown): SweepRow[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const row = obj(item);
    const pair = toPair(row);
    if (!row || !pair) return [];
    return [{
      pair, recall: toRate(row.recall), missed: num(row.missed) ?? 0, lost: num(row.lost_vs_llm) ?? 0,
      lostIds: Array.isArray(row.lost_ids) ? row.lost_ids.filter((x): x is string => typeof x === "string") : [],
      callsSaved: num(row.calls_saved) ?? 0, escalated: num(row.escalated) ?? 0,
    }];
  });
}

export function parseEval(metrics: Json): EvalView {
  const gold = obj(metrics.gold);
  const strategies = obj(metrics.strategies) ?? {};
  const holdout = obj(metrics.holdout);
  const holdoutSweep = obj(metrics.holdout_sweep);
  const rejected = obj(metrics.rejected_on_holdout);
  const agreement = obj(metrics.agreement);
  const verdict = obj(agreement?.verdict);
  return {
    gold: { name: str(gold?.name, "unknown"), citation: str(gold?.citation) },
    screened: num(obj(metrics.counts)?.screened),
    retrievalRecall: toRate(metrics.retrieval_recall),
    defaultPair: toPair(metrics.default_thresholds),
    strategies: (["llm_only", "jev_only", "cascade"] as const).flatMap((name) => {
      const s = obj(strategies[name]);
      return s ? [{ name, recall: toRate(s.recall), callsSaved: num(s.calls_saved) ?? 0, escalated: num(s.escalated) ?? 0, kept: num(s.kept) ?? 0, keptNegatives: num(s.kept_negatives) ?? 0 }] : [];
    }),
    sweep: toRows(metrics.sweep),
    holdout: holdout ? { gold: str(holdout.gold), n: num(holdout.n) ?? 0, recall: toRate(holdout.recall), pair: toPair(holdout.thresholds), callsSaved: num(holdout.calls_saved) } : null,
    holdoutSweep: holdoutSweep ? { gold: str(holdoutSweep.gold), n: num(holdoutSweep.n) ?? 0, rows: toRows(holdoutSweep.rows) } : null,
    recommended: toPair(metrics.recommended),
    rejected: rejected && toPair(rejected.thresholds)
      ? {
          pair: toPair(rejected.thresholds)!,
          lost: Array.isArray(rejected.lost) ? rejected.lost.flatMap((m) => { const o = obj(m); return o ? [{ id: str(o.id), title: str(o.title) }] : []; }) : [],
        }
      : null,
    agreement: agreement
      ? { n: num(agreement.n) ?? 0, kappa: num(verdict?.kappa), agreement: num(verdict?.agreement), reason: typeof verdict?.reason === "string" ? verdict.reason : null, sameFamily: typeof agreement.same_family === "boolean" ? agreement.same_family : null, adjudicated: toRate(agreement.adjudication_rate) }
      : null,
    warnings: Array.isArray(metrics.warnings) ? metrics.warnings.filter((w): w is string => typeof w === "string") : [],
  };
}

export function formatRate(rate: Rate | null): string {
  if (!rate) return "n/a";
  if (rate.value === null || !rate.ci) return `n/a (${rate.reason ?? "undefined"})`;
  return `${rate.k}/${rate.n} (95% CI ${rate.ci[0].toFixed(2)}–${rate.ci[1].toFixed(2)})`;
}

export const rowFor = (rows: SweepRow[], pair: Pair): SweepRow | undefined =>
  rows.find((row) => row.pair.include === pair.include && row.pair.exclude === pair.exclude);

export const samePair = (a: Pair | null, b: Pair | null) => !!a && !!b && a.include === b.include && a.exclude === b.exclude;
```

- [ ] **Step 5: Write the failing page tests**

`web/src/pages/EvalsPage.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { EVAL_ID, evalDetail, evalMetrics, evalSummary, session } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { EvalsPage } from "./EvalsPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

function setup(detail = evalDetail(), summaries = [evalSummary()]) {
  const api = mockApi({
    "GET /api/v1/auth/me": { body: session("viewer") },
    "GET /api/v1/evals": { body: summaries },
    "GET /api/v1/evals/:id": { body: detail },
  });
  renderWithProviders(<Routes><Route path="/evals" element={<EvalsPage />} /><Route path="/evals/:evalId" element={<EvalsPage />} /></Routes>, { route: "/evals" });
  return api;
}

describe("EvalsPage", () => {
  it("opens the newest eval set and shows the summary cards with the exact numbers", async () => {
    setup();
    expect(await screen.findByRole("heading", { name: /mlffrct-2024/ })).toBeInTheDocument();
    const cards = screen.getByRole("region", { name: "Summary" });
    expect(within(cards).getByText("15/16 (95% CI 0.72–0.99)", { exact: false })).toBeInTheDocument();
    expect(within(cards).getByText("include ≥ 0.1, exclude ≥ 0.7")).toBeInTheDocument();
    expect(within(cards).getByText("0.945")).toBeInTheDocument();
    expect(within(cards).getByText("same model family")).toBeInTheDocument();
  });

  it("shows recall for the three strategies with intervals", async () => {
    setup();
    const rows = await screen.findByRole("table", { name: "Recall by strategy" });
    expect(within(rows).getByRole("row", { name: /cascade/ })).toHaveTextContent("15/16");
    expect(within(rows).getByRole("row", { name: /jev_only/ })).toHaveTextContent("14/16");
    expect(within(rows).getByRole("row", { name: /llm_only/ })).toHaveTextContent("0 calls saved");
  });

  it("draws the threshold grid: default outlined, recommended starred, risky pairs marked in words", async () => {
    setup();
    const grid = await screen.findByRole("table", { name: "Threshold grid" });
    const cell = (include: string, exclude: string) => within(grid).getByRole("cell", { name: new RegExp(`^include ${include}, exclude ${exclude}:`) });
    expect(cell("0.6", "0.9")).toHaveClass("is-default");
    expect(cell("0.6", "0.9")).toHaveTextContent("69");
    expect(cell("0.1", "0.7")).toHaveTextContent("★");
    expect(cell("0.1", "0.7")).toHaveTextContent("74");
    expect(cell("0.1", "0.5")).toHaveClass("is-risky");
    expect(cell("0.1", "0.5")).toHaveTextContent("loses 1 on the main set");
    expect(cell("0.6", "0.99")).toHaveClass("is-risky");
    expect(cell("0.6", "0.99")).toHaveTextContent("loses 1 on the holdout");
  });

  it("empty combinations are cells that say they are not allowed, not blanks", async () => {
    setup();
    const grid = await screen.findByRole("table", { name: "Threshold grid" });
    expect(within(grid).getAllByText("–").length).toBeGreaterThan(0);
  });

  it("explains the rejected pick and lists the caveats", async () => {
    setup();
    const banner = await screen.findByText(/Rejected on the holdout/);
    expect(banner).toHaveTextContent("include ≥ 0.1, exclude ≥ 0.5");
    expect(banner).toHaveTextContent("A holdout paper the pair would lose");
    expect(screen.getByRole("list", { name: "Caveats" })).toHaveTextContent("Rejected.");
  });

  it("says when the grid has no holdout to check against, and when nothing is recommended", async () => {
    setup(evalDetail({ ...evalMetrics(), holdout_sweep: null, holdout: null, rejected_on_holdout: null, recommended: null }));
    expect(await screen.findByText(/No holdout run: risky pairs can only be judged on the main set/)).toBeInTheDocument();
    expect(screen.getByText("No admissible pair")).toBeInTheDocument();
  });

  it("switches between eval sets", async () => {
    const second = evalSummary({ id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", gold_set: { id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", name: "aiffr-slr-2023", citation: "Other 2023" } });
    const { calls } = setup(evalDetail(), [evalSummary(), second]);
    await screen.findByRole("heading", { name: /mlffrct-2024/ });
    await userEvent.selectOptions(screen.getByLabelText("Eval set"), second.id);
    expect(calls.some((c) => c.path === `/api/v1/evals/${second.id}`)).toBe(true);
    expect(calls.some((c) => c.path === `/api/v1/evals/${EVAL_ID}`)).toBe(true);
  });

  it("says so when there are no eval reports", async () => {
    setup(evalDetail(), []);
    expect(await screen.findByText(/No eval reports yet/)).toBeInTheDocument();
  });

  it("shows the request id when the report cannot be loaded", async () => {
    mockApi({
      "GET /api/v1/auth/me": { body: session("viewer") },
      "GET /api/v1/evals": { body: [evalSummary()] },
      "GET /api/v1/evals/:id": { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "req-9" } },
    });
    renderWithProviders(<Routes><Route path="/evals" element={<EvalsPage />} /></Routes>, { route: "/evals" });
    expect(await screen.findByRole("alert")).toHaveTextContent("req-9");
  });
});
```

- [ ] **Step 6: Run to verify failure**

Run: `npm test -- src/pages/EvalsPage.test.tsx`
Expected: FAIL, `Failed to resolve import "./EvalsPage"`.

- [ ] **Step 7: Implement the recall table, the grid and the page**

`web/src/features/evals/RecallRows.tsx`:

```tsx
import { formatRate, type Strategy } from "./metrics";

const LABEL: Record<Strategy["name"], string> = {
  llm_only: "llm_only (the LLM screens everything)",
  jev_only: "jev_only (Jev alone, no LLM)",
  cascade: "cascade (Jev when confident, else the LLM)",
};

/** A dot-and-interval bar on a fixed 0 to 1 axis, next to the numbers as text. */
function Interval({ recall }: { recall: Strategy["recall"] }) {
  if (!recall || recall.value === null || !recall.ci) return <span className="na" aria-hidden="true">–</span>;
  const [low, high] = recall.ci;
  return (
    <svg viewBox="0 0 100 12" width="160" height="16" role="img" aria-label={`recall ${recall.value.toFixed(2)}, interval ${low.toFixed(2)} to ${high.toFixed(2)}`}>
      <line x1="0" y1="6" x2="100" y2="6" className="axis" />
      <line x1={low * 100} y1="6" x2={high * 100} y2="6" className="interval" />
      <circle cx={recall.value * 100} cy="6" r="3.5" className="dot" />
    </svg>
  );
}

export function RecallRows({ strategies }: { strategies: Strategy[] }) {
  return (
    <table className="recall" aria-label="Recall by strategy">
      <thead><tr><th scope="col">Strategy</th><th scope="col">Recall on SR-included papers</th><th scope="col">Interval (0 to 1)</th><th scope="col">Workload</th></tr></thead>
      <tbody>
        {strategies.map((s) => (
          <tr key={s.name}>
            <th scope="row">{LABEL[s.name]}</th>
            <td>{formatRate(s.recall)}</td>
            <td><Interval recall={s.recall} /></td>
            <td>{s.callsSaved} calls saved · {s.escalated} escalated · {s.kept} kept ({s.keptNegatives} not in the SR)</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

`web/src/features/evals/ThresholdGrid.tsx`:

```tsx
import { rowFor, samePair, type EvalView, type Pair } from "./metrics";

const INCLUDES = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9];
const EXCLUDES = [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99];

/** Rows are the include threshold, columns the exclude threshold, a cell is the screening calls saved. */
export function ThresholdGrid({ view }: { view: EvalView }) {
  const holdout = view.holdoutSweep;
  return (
    <div>
      <table className="grid" aria-label="Threshold grid">
        <thead>
          <tr><th scope="col">include ↓ / exclude →</th>{EXCLUDES.map((e) => <th key={e} scope="col">{e}</th>)}</tr>
        </thead>
        <tbody>
          {INCLUDES.map((include) => (
            <tr key={include}>
              <th scope="row">{include}</th>
              {EXCLUDES.map((exclude) => {
                const pair: Pair = { include, exclude };
                const main = rowFor(view.sweep, pair);
                if (!main) return <td key={exclude} className="not-allowed" title="The exclude bar cannot be lower than the include bar">–</td>;
                const other = holdout ? rowFor(holdout.rows, pair) : undefined;
                const isDefault = samePair(view.defaultPair, pair);
                const isRecommended = samePair(view.recommended, pair);
                const risks = [main.lost > 0 && `loses ${main.lost} on the main set`, other && other.lost > 0 && `loses ${other.lost} on the holdout`].filter(Boolean) as string[];
                const label = `include ${include}, exclude ${exclude}: ${main.callsSaved} calls saved${isDefault ? ", shipped default" : ""}${isRecommended ? ", recommended" : ""}${risks.length ? `, ${risks.join(", ")}` : ""}`;
                return (
                  <td key={exclude} aria-label={label} className={[isDefault && "is-default", risks.length > 0 && "is-risky"].filter(Boolean).join(" ")}>
                    <span>{main.callsSaved}</span>{isRecommended && <span aria-hidden="true"> ★</span>}
                    {risks.map((risk) => <span key={risk} className="risk">{risk}</span>)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="legend">
        Cells show screening calls saved by the cascade. Outlined = shipped default. ★ = recommended (loses no SR-included paper on the main set or the holdout). Red with text = the pair loses an SR-included paper that llm_only keeps.
        {!holdout && " No holdout run: risky pairs can only be judged on the main set."}
      </p>
    </div>
  );
}
```

(`aria-label` on a `td` overrides its text for the accessible name; the tests read `getByRole("cell", { name })` and the visible text separately, and both hold. If a linter rule complains about `aria-label` on `td`, use `title` plus visually-hidden text instead and keep the tests unchanged.)

`web/src/pages/EvalsPage.tsx`:

```tsx
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useEval, useEvals } from "../api/hooks";
import { formatRate, parseEval } from "../features/evals/metrics";
import { RecallRows } from "../features/evals/RecallRows";
import { ThresholdGrid } from "../features/evals/ThresholdGrid";

const pairText = (pair: { include: number; exclude: number }) => `include ≥ ${pair.include}, exclude ≥ ${pair.exclude}`;

export function EvalsPage() {
  const { evalId } = useParams();
  const navigate = useNavigate();
  const evals = useEvals();
  const selected = evalId ?? evals.data?.[0]?.id ?? null;
  const detail = useEval(selected);

  if (evals.isLoading) return <p role="status">Loading…</p>;
  if (evals.isError) return <p role="alert">Could not load the eval reports.</p>;
  if (!evals.data?.length) return <section><h1>Evals</h1><p>No eval reports yet. Import an eval folder with <code>research-web import</code>.</p></section>;

  const view = detail.data ? parseEval(detail.data.metrics) : null;
  return (
    <section>
      <h1>Evals</h1>
      <label>Eval set
        <select value={selected ?? ""} onChange={(e) => navigate(`/evals/${e.target.value}`)}>
          {evals.data.map((e) => <option key={e.id} value={e.id}>{e.gold_set.name}</option>)}
        </select>
      </label>
      {detail.isError && <p role="alert" className="form-error">{detail.error instanceof ApiError ? `${detail.error.message} (request ${detail.error.requestId})` : "Could not load this report."}</p>}
      {view && (
        <>
          <h2>{view.gold.name} <span className="sub">{view.gold.citation}</span></h2>
          <section aria-label="Summary" className="cards">
            <div className="card"><h3>Search recall</h3><p>{formatRate(view.retrievalRecall)}</p><p className="sub">SR-included papers the query itself found</p></div>
            <div className="card"><h3>Recommended pair</h3><p>{view.recommended ? pairText(view.recommended) : "No admissible pair"}</p><p className="sub">{view.recommended ? "loses no SR-included paper on the main set or the holdout" : "every pair loses a paper that llm_only keeps"}</p></div>
            <div className="card"><h3>Reviewer agreement (kappa)</h3><p>{view.agreement ? (view.agreement.kappa === null ? `n/a (${view.agreement.reason ?? "undefined"})` : view.agreement.kappa.toFixed(3)) : "n/a"}</p>
              <p className="sub">{view.agreement ? `${view.agreement.n} papers` : "no agreement run"}{view.agreement?.sameFamily ? " · " : ""}{view.agreement?.sameFamily && <span className="chip chip--warn">same model family</span>}</p></div>
          </section>
          <h3>Recall</h3>
          <RecallRows strategies={view.strategies} />
          {view.holdout && <p>Holdout ({view.holdout.gold}, {view.holdout.n} papers) at the recommended pair: recall {formatRate(view.holdout.recall)}.</p>}
          <h3>Threshold grid</h3>
          <ThresholdGrid view={view} />
          {view.rejected && (
            <p className="banner banner--warn">
              Rejected on the holdout: {pairText(view.rejected.pair)} is best on the main set but loses {view.rejected.lost.length} SR-included paper(s) there that llm_only keeps:{" "}
              {view.rejected.lost.map((m) => m.title).join("; ")}.
            </p>
          )}
          {view.warnings.length > 0 && <ul aria-label="Caveats">{view.warnings.map((w) => <li key={w}>{w}</li>)}</ul>}
        </>
      )}
    </section>
  );
}
```

Two details to keep straight in the tests above: the `rejected` sentence contains the text "Rejected on the holdout", and the warning text from `metrics.json` also ends with "Rejected." (the `findByText(/Rejected on the holdout/)` match is the banner only).

In `App.tsx` import `EvalsPage` from `./pages/EvalsPage`; remove its line from `PlaceholderPages.tsx`. Append to `styles.css`:

```css
.cards { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin: 12px 0; }
.card { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: var(--panel); }
.card h3 { margin: 0 0 4px; font-size: 12px; color: var(--muted); font-weight: 600; }
.card p { margin: 0; }
table.recall, table.grid { border-collapse: collapse; }
table.recall th, table.recall td, table.grid th, table.grid td { padding: 6px 10px; border: 1px solid var(--line); text-align: left; }
table.grid td { text-align: center; min-width: 72px; vertical-align: top; }
table.grid td.is-default { outline: 2px solid var(--accent); outline-offset: -2px; }
table.grid td.is-risky { background: var(--bad-bg); color: var(--bad-fg); }
table.grid td.not-allowed { color: var(--muted); background: var(--panel); }
.risk { display: block; font-size: 10px; }
.legend { color: var(--muted); font-size: 12px; max-width: 70ch; }
svg .axis { stroke: var(--line); stroke-width: 1; }
svg .interval { stroke: var(--accent); stroke-width: 3; }
svg .dot { fill: var(--accent); }
.banner--warn { border-left-color: var(--warn-line); background: var(--warn-bg); color: var(--warn-fg); }
```

- [ ] **Step 8: Run and commit**

Run: `npm run typecheck && npm run lint && npm test && npm run build`
Expected: green.

```bash
cd .. && git add -A
git commit -m "Add the Evals page with recall intervals and the threshold grid" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 10: System map page

**Files:**
- Create: `web/src/pages/SystemMapPage.tsx`, `web/src/features/system/SystemMap.tsx`
- Modify: `web/src/App.tsx`, `web/src/pages/PlaceholderPages.tsx`, `web/src/styles.css`
- Test: `web/src/pages/SystemMapPage.test.tsx`

The pipeline as clickable boxes in order, each with a status in words. A box is green only when `status === "measured"`; `caveat` and `unmeasured` are amber; `input` is neutral. The selected stage opens the same `StagePanel` used on the Papers page, with links into the data. The selected stage lives in the URL (`?stage=`).

- [ ] **Step 1: Write the failing tests**

`web/src/pages/SystemMapPage.test.tsx`:

```tsx
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../api/client";
import { session, STAGES } from "../test/fixtures";
import { mockApi } from "../test/mockApi";
import { renderWithProviders } from "../test/render";
import { SystemMapPage } from "./SystemMapPage";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
});

const Location = () => <output aria-label="location">{useLocation().search}</output>;

function setup(route = "/system", stages: unknown = STAGES) {
  const api = mockApi({ "GET /api/v1/auth/me": { body: session("viewer") }, "GET /api/v1/stages": typeof stages === "object" && stages && "status" in (stages as object) ? (stages as never) : { body: stages } });
  renderWithProviders(<><Routes><Route path="/system" element={<SystemMapPage />} /></Routes><Location /></>, { route });
  return api;
}

describe("SystemMapPage", () => {
  it("shows every stage in pipeline order with its status in words", async () => {
    setup();
    const list = await screen.findByRole("list", { name: "Pipeline" });
    const items = within(list).getAllByRole("listitem");
    expect(items.map((li) => li.querySelector(".stage-title")?.textContent)).toEqual(STAGES.map((s) => s.title));
    const box = (title: string) => within(list).getByRole("button", { name: new RegExp(`^${title}`) });
    expect(box("Search")).toHaveAttribute("data-status", "measured");
    expect(box("Search")).toHaveTextContent("recall 15/16");
    expect(box("Reviewers A and B")).toHaveAttribute("data-status", "caveat");
    expect(box("Reviewers A and B")).toHaveTextContent("one model family");
    expect(box("Rank")).toHaveAttribute("data-status", "unmeasured");
    expect(box("Rank")).toHaveTextContent("not measured");
    expect(box("Topic")).toHaveAttribute("data-status", "input");
  });

  it("a stage opens its panel and the choice is in the URL", async () => {
    setup();
    await userEvent.click(await screen.findByRole("button", { name: /^Screen/ }));
    const panel = await screen.findByRole("complementary", { name: "About Screen" });
    expect(within(panel).getByText(/Jev decides when confident/)).toBeInTheDocument();
    expect(within(panel).getByText("Abstract only.")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "See the screened papers" })).toHaveAttribute("href", "/");
    expect(screen.getByLabelText("location")).toHaveTextContent("stage=screen");
  });

  it("opens straight to a stage from the URL and closes it again", async () => {
    setup("/system?stage=reviewers");
    const panel = await screen.findByRole("complementary", { name: "About Reviewers A and B" });
    expect(within(panel).getByRole("link", { name: "Open the eval report" })).toHaveAttribute("href", "/evals");
    await userEvent.click(within(panel).getByRole("button", { name: "Close stage details" }));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.getByLabelText("location")).not.toHaveTextContent("stage=");
  });

  it("ignores an unknown stage id in the URL", async () => {
    setup("/system?stage=nope");
    await screen.findByRole("list", { name: "Pipeline" });
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  });

  it("says why when the catalog cannot be loaded", async () => {
    setup("/system", { status: 500, body: { code: "internal_error", message: "Unexpected error", request_id: "req-3" } });
    expect(await screen.findByRole("alert")).toHaveTextContent("req-3");
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npm test -- src/pages/SystemMapPage.test.tsx`
Expected: FAIL, `Failed to resolve import "./SystemMapPage"`.

- [ ] **Step 3: Implement**

`web/src/features/system/SystemMap.tsx`:

```tsx
import type { StageOut } from "../../api/types";
import { statusText } from "../papers/PipelineStrip";

export function SystemMap({ stages, selectedId, onSelect }: { stages: StageOut[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <ol className="pipeline" aria-label="Pipeline">
      {stages.map((stage, index) => (
        <li key={stage.id}>
          <button type="button" className={`stage stage--${stage.status}`} data-status={stage.status} aria-pressed={selectedId === stage.id} onClick={() => onSelect(stage.id)}>
            <span className="stage-index" aria-hidden="true">{index + 1}</span>
            <span className="stage-title">{stage.title}</span>
            <span className="stage-status">{statusText(stage)}</span>
            {stage.headline && <span className="stage-headline">{stage.headline}</span>}
          </button>
        </li>
      ))}
    </ol>
  );
}
```

`web/src/pages/SystemMapPage.tsx`:

```tsx
import { useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { useStages } from "../api/hooks";
import { StagePanel } from "../features/papers/StagePanel";
import { SystemMap } from "../features/system/SystemMap";

export function SystemMapPage() {
  const [search, setSearch] = useSearchParams();
  const stages = useStages();
  const selectedId = search.get("stage");
  const select = (id: string | null) => {
    const next = new URLSearchParams(search);
    if (id && id !== selectedId) next.set("stage", id);
    else next.delete("stage");
    setSearch(next);
  };

  if (stages.isLoading) return <p role="status">Loading…</p>;
  if (stages.isError) return <p role="alert">{stages.error instanceof ApiError ? `${stages.error.message} (request ${stages.error.requestId})` : "Could not load the system map."}</p>;
  const selected = stages.data?.find((stage) => stage.id === selectedId);

  return (
    <section>
      <h1>System map</h1>
      <p className="sub">Each stage is teal only when a measurement exists. Amber means a caveat applies or nothing has measured it yet.</p>
      <div className={`papers-layout ${selected ? "with-panel" : ""}`}>
        <SystemMap stages={stages.data ?? []} selectedId={selected?.id ?? null} onSelect={select} />
        {selected && <StagePanel stage={selected} onClose={() => select(null)} showPapersLink />}
      </div>
    </section>
  );
}
```

In `App.tsx` import `SystemMapPage` from `./pages/SystemMapPage`; remove its line from `PlaceholderPages.tsx`. Append to `styles.css`:

```css
ol.pipeline { list-style: none; margin: 12px 0; padding: 0; display: grid; gap: 8px; }
ol.pipeline .stage { width: 100%; display: grid; grid-template-columns: 28px 1fr auto; gap: 2px 10px; align-items: center; text-align: left; border: 1px solid var(--line); border-left-width: 6px; border-radius: 8px; padding: 8px 12px; }
ol.pipeline .stage-status { grid-column: 3; font-size: 12px; }
ol.pipeline .stage-headline { grid-column: 2 / 4; font-size: 12px; }
ol.pipeline .stage--measured { background: var(--ok-bg); color: var(--ok-fg); border-left-color: var(--ok-line); }
ol.pipeline .stage--caveat, ol.pipeline .stage--unmeasured { background: var(--warn-bg); color: var(--warn-fg); border-left-color: var(--warn-line); }
ol.pipeline .stage--input { background: var(--neutral-bg); color: var(--neutral-fg); }
ol.pipeline .stage[aria-pressed="true"] { outline: 2px solid var(--accent); }
```

- [ ] **Step 4: Run and commit**

Run: `npm run typecheck && npm run lint && npm test && npm run build`
Expected: green.

```bash
cd .. && git add -A
git commit -m "Add the System map page" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 11: Users page (admin)

**Files:**
- Create: `web/src/pages/UsersPage.tsx`, `web/src/features/users/InviteForm.tsx`
- Modify: `web/src/App.tsx`, `web/src/pages/PlaceholderPages.tsx` (delete the file: it is now empty), `web/src/test/fixtures.ts`
- Test: `web/src/pages/UsersPage.test.tsx`

An admin lists users, invites one (email, name, role, initial password of at least 12 characters that the admin hands over out of band), changes a role and deactivates or reactivates an account. The backend refuses to demote or deactivate the last admin and returns 409; the page shows its message. The route is already behind `RequireRole role="admin"` (Task 3).

- [ ] **Step 1: Add a user-list fixture (append to `web/src/test/fixtures.ts`)**

```ts
export const userRows = (): UserOut[] => [
  { id: "10000000-0000-4000-8000-000000000001", email: "admin@example.org", name: "Ada Admin", role: "admin", active: true },
  { id: "10000000-0000-4000-8000-000000000002", email: "member@example.org", name: "Mia Member", role: "member", active: true },
  { id: "10000000-0000-4000-8000-000000000003", email: "old@example.org", name: "Olga Old", role: "viewer", active: false },
];
```

(Make sure `UserOut` is imported at the top of the file; Task 3's fixtures already import it.)

- [ ] **Step 2: Write the failing tests**

`web/src/pages/UsersPage.test.tsx`:

```tsx
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
    setup({ "PATCH /api/v1/users/:id": { status: 409, body: { code: "conflict", message: "The last active admin cannot be demoted or deactivated", request_id: "r" } } });
    await userEvent.click(await screen.findByRole("button", { name: "Deactivate admin@example.org" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("last active admin");
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
    setup({ "POST /api/v1/users": { status: 409, body: { code: "conflict", message: "A user with this email already exists", request_id: "r" } } });
    await screen.findByRole("table");
    await userEvent.type(screen.getByLabelText("Email"), "member@example.org");
    await userEvent.type(screen.getByLabelText("Name"), "Dup");
    await userEvent.type(screen.getByLabelText("Initial password"), "a-long-enough-password");
    await userEvent.click(screen.getByRole("button", { name: "Invite" }));
    expect(await screen.findByText(/already exists/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run to verify failure**

Run: `npm test -- src/pages/UsersPage.test.tsx`
Expected: FAIL, `Failed to resolve import "./UsersPage"`.

- [ ] **Step 4: Implement**

`web/src/features/users/InviteForm.tsx`:

```tsx
import { useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useCreateUser } from "../../api/hooks";

export function InviteForm() {
  const create = useCreateUser();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("member");
  const [password, setPassword] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!email || !name) return setProblem("Email and name are required.");
    if (password.length < 12) return setProblem("The password needs at least 12 characters.");
    setProblem(null);
    try {
      await create.mutateAsync({ email, name, role, password });
      setEmail("");
      setName("");
      setPassword("");
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };

  return (
    <form onSubmit={submit} className="start-run" aria-label="Invite a user">
      <label>Email<input type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
      <label>Name<input autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} /></label>
      <label>Role
        <select value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="viewer">viewer</option><option value="member">member</option><option value="admin">admin</option>
        </select>
      </label>
      <label>Initial password<input type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
      <button type="submit" disabled={create.isPending}>Invite</button>
      {problem && <p role="alert" className="form-error">{problem}</p>}
    </form>
  );
}
```

`web/src/pages/UsersPage.tsx`:

```tsx
import { useState } from "react";

import { ApiError } from "../api/client";
import { usePatchUser, useUsers } from "../api/hooks";
import { InviteForm } from "../features/users/InviteForm";

export function UsersPage() {
  const users = useUsers();
  const patch = usePatchUser();
  const [problem, setProblem] = useState<string | null>(null);

  const change = async (id: string, body: { role?: string; active?: boolean }) => {
    setProblem(null);
    try {
      await patch.mutateAsync({ id, ...body });
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };

  if (users.isLoading) return <p role="status">Loading…</p>;
  if (users.isError) return <p role="alert">Could not load the users.</p>;
  return (
    <section>
      <h1>Users</h1>
      <InviteForm />
      {problem && <p role="alert" className="form-error">{problem}</p>}
      <table className="runs">
        <thead><tr><th scope="col">Email</th><th scope="col">Name</th><th scope="col">Role</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
        <tbody>
          {users.data?.map((user) => (
            <tr key={user.id}>
              <td>{user.email}</td>
              <td>{user.name}</td>
              <td>
                <select aria-label={`Role for ${user.email}`} value={user.role} onChange={(e) => change(user.id, { role: e.target.value })}>
                  <option value="viewer">viewer</option><option value="member">member</option><option value="admin">admin</option>
                </select>
              </td>
              <td>{user.active ? "active" : "inactive"}</td>
              <td>
                <button type="button" onClick={() => change(user.id, { active: !user.active })}>
                  {user.active ? "Deactivate" : "Reactivate"}<span className="sr-only"> {user.email}</span>
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
```

In `App.tsx` import `UsersPage` from `./pages/UsersPage` and delete `web/src/pages/PlaceholderPages.tsx` (every page is real now); remove its import.

(The accessible name of the action button is "Deactivate member@example.org" because the visually-hidden span is part of the button's text.)

- [ ] **Step 5: Run and commit**

Run: `npm run typecheck && npm run lint && npm test && npm run build`
Expected: green; the whole unit suite passes with no placeholder pages left.

```bash
cd .. && git add -A
git commit -m "Add the Users page and remove the placeholder pages" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---
### Task 12: Production image: nginx, a strict CSP and the `web` service

**Files:**
- Create: `deploy/nginx.conf`, `deploy/Dockerfile.web`, `web/src/security.test.ts`
- Modify: `deploy/docker-compose.yml`, `.dockerignore`, `tests/test_web_deploy.py`, `docs/deployment.md`
- Test: `web/src/security.test.ts`, `tests/test_web_deploy.py`

The browser talks to one origin: nginx serves the built app and proxies `/api/` to the `api` service. That makes cookies and CSRF same-origin and lets the Content-Security-Policy be `'self'` only, which is only possible if the app never uses inline scripts, inline styles or `innerHTML`. A frontend test enforces that; the nginx and compose rules are tested as data (Docker is not available on the development machine).

- [ ] **Step 1: Write the failing frontend test**

`web/src/security.test.ts`:

```ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const sources = walk("src").filter((path) => /\.(ts|tsx)$/.test(path) && !path.endsWith(".test.ts") && !path.endsWith(".test.tsx") && !path.includes("/test/") && !path.endsWith("schema.d.ts"));

describe("what the Content-Security-Policy relies on", () => {
  it("finds the source files", () => {
    expect(sources.length).toBeGreaterThan(20);
  });

  it("uses no inline style attributes (the CSP has no 'unsafe-inline' for styles)", () => {
    const offenders = sources.filter((path) => /\bstyle=\{/.test(readFileSync(path, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("never injects HTML and never evaluates strings", () => {
    const offenders = sources.filter((path) => /dangerouslySetInnerHTML|\.innerHTML\s*=|\beval\(|new Function\(/.test(readFileSync(path, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("index.html has one external module script and no inline script or style", () => {
    const html = readFileSync("index.html", "utf8");
    expect(html.match(/<script\b[^>]*>/g)?.every((tag) => /\bsrc=/.test(tag))).toBe(true);
    expect(html).not.toMatch(/<style\b/);
    expect(html).not.toMatch(/\son[a-z]+=/i);
  });
});
```

- [ ] **Step 2: Run to verify it passes or shows real offenders**

Run: `npm test -- src/security.test.ts`
Expected: PASS if the earlier tasks kept to the rules. If it fails, fix the offending component (use a CSS class, not a `style` attribute); do not weaken the test.

- [ ] **Step 3: Write the failing deployment tests**

In `tests/test_web_deploy.py`, replace `test_services_and_startup_order` and `test_only_the_api_publishes_a_port_and_only_on_loopback`, and append the new tests below.

```python
def test_services_and_startup_order(compose):
    services = compose["services"]
    assert set(services) == {"db", "migrate", "api", "worker", "web"}
    assert services["api"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["worker"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert services["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert "healthcheck" in services["db"] and "healthcheck" in services["api"]


def test_only_the_web_service_publishes_a_port_and_only_on_loopback(compose):
    for name, service in compose["services"].items():
        ports = service.get("ports", [])
        if name == "web":
            assert ports == ["127.0.0.1:8080:8080"]
        else:
            assert not ports, f"{name} must not publish ports; the browser reaches the API through nginx"
    assert compose["services"]["api"]["expose"] == ["8000"]


def test_the_web_container_is_unprivileged_and_read_only(compose):
    web = compose["services"]["web"]
    assert web["read_only"] is True and web["tmpfs"] == ["/tmp"]
    assert "env_file" not in web and not (web.get("environment") or {})
    text = (ROOT / "deploy" / "Dockerfile.web").read_text()
    assert "nginx-unprivileged" in text and "npm ci" in text and not re.search(r"COPY[^\n]*\.env", text)


NGINX = ROOT / "deploy" / "nginx.conf"


def test_nginx_serves_the_app_and_proxies_only_the_api():
    text = NGINX.read_text()
    assert "listen 8080;" in text and "server_tokens off;" in text
    assert "proxy_pass http://api:8000;" in text
    assert "try_files $uri /index.html;" in text  # client-side routes
    assert text.count("proxy_pass") == 1


def test_nginx_csp_is_strict():
    text = NGINX.read_text()
    policy = re.search(r"add_header Content-Security-Policy \"([^\"]+)\" always;", text).group(1)
    for directive in ("default-src 'self'", "script-src 'self'", "style-src 'self'", "connect-src 'self'", "frame-ancestors 'none'", "base-uri 'none'", "form-action 'self'", "object-src 'none'"):
        assert directive in policy
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy and "*" not in policy
    for header in ("X-Content-Type-Options nosniff", "Referrer-Policy no-referrer", "X-Frame-Options DENY"):
        assert f"add_header {header} always;" in text


def test_nginx_locations_do_not_reset_the_security_headers():
    # nginx drops inherited add_header directives in any block that defines its own; keep them at server level only.
    text = NGINX.read_text()
    for block in re.findall(r"location[^{]*\{[^}]*\}", text):
        assert "add_header" not in block, block
    api_block = re.search(r"location /api/ \{[^}]*\}", text).group(0)
    for name in ("Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options"):
        assert f"proxy_hide_header {name};" in api_block  # one source of truth at the edge
```

- [ ] **Step 4: Run to verify failure**

Run: `pytest tests/test_web_deploy.py -v`
Expected: FAIL (`deploy/nginx.conf` and `Dockerfile.web` do not exist; compose has no `web` service).

- [ ] **Step 5: Write `deploy/nginx.conf`**

```nginx
server {
    listen 8080;
    server_name _;
    server_tokens off;
    root /usr/share/nginx/html;
    index index.html;
    client_max_body_size 1m;

    # Security headers live at server level only: a block that defines its own add_header drops these.
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;
    add_header X-Frame-Options DENY always;

    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_hide_header Content-Security-Policy;
        proxy_hide_header X-Content-Type-Options;
        proxy_hide_header Referrer-Policy;
        proxy_hide_header X-Frame-Options;
        proxy_read_timeout 30s;
    }

    location /assets/ {
        expires 1y;
        try_files $uri =404;
    }

    location = /index.html {
        expires -1;
    }

    location / {
        try_files $uri /index.html;
    }
}
```

- [ ] **Step 6: Write `deploy/Dockerfile.web`**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
```

(`web/package-lock.json` was created by `npm install` in Task 0 and committed; `npm ci` fails without it.)

- [ ] **Step 7: Update `deploy/docker-compose.yml` and `.dockerignore`**

In the `api` service, replace the `ports:` block with:

```yaml
    expose:
      - "8000"
```

Add the `web` service after `worker`:

```yaml
  web:
    build:
      context: ..
      dockerfile: deploy/Dockerfile.web
    depends_on:
      api:
        condition: service_healthy
    ports:
      - "127.0.0.1:8080:8080"
    read_only: true
    tmpfs:
      - /tmp
    restart: unless-stopped
```

Append to `.dockerignore`: `web/dist`, `web/playwright-report`, `web/test-results`, `web/e2e/.auth`.

In `docs/deployment.md` change every mention of the published API port: the only published port is now `127.0.0.1:8080` (the `web` service); the TLS reverse proxy in front points there, and `research-web` `create-admin` and `import` still run as one-off `docker compose run` commands. Add one sentence: the Content-Security-Policy is set by nginx and is `'self'` only, so do not add third-party scripts, fonts or analytics without changing it deliberately.

- [ ] **Step 8: Run and commit**

Run: `pytest tests/test_web_deploy.py -q && (cd web && npm test)`
Expected: the deploy tests pass (the earlier 7 minus the 2 replaced, plus the new ones) and all frontend tests pass.

```bash
ruff format src tests && ruff check . && git add -A
git commit -m "Add the nginx web image with a strict CSP and tests for it" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 13: End-to-end and accessibility tests in a real browser

**Files:**
- Create: `scripts/e2e_server.py`, `tests/test_web_e2e_server.py`, `web/playwright.config.ts`, `web/e2e/users.ts`, `web/e2e/auth.setup.ts`, `web/e2e/flows.spec.ts`, `web/e2e/a11y.spec.ts`
- Modify: `web/vite.config.ts`, `web/.gitignore`, `.gitignore`

The browser tests run the real API, the real worker and the built frontend against a small synthetic dataset (the same helpers the backend tests use). Nothing here touches the network or an API key; the runs are demo mode. The dataset is what makes the story testable: in the toy eval set, paper `MED:3` is in the systematic review and the screen drops it (Jev p = 0.03), the same shape as the real ΔCT-FFR paper.

- [ ] **Step 1: Write the failing test for the seed script**

`tests/test_web_e2e_server.py`:

```python
import importlib.util
from pathlib import Path

from sqlalchemy import func, select

from research_agent.web.db.models import Paper, Run, Screening, User
from research_agent.web.db.session import make_engine, make_session_factory
from research_agent.web.settings import load_settings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "e2e_server.py"


def load_script():
    spec = importlib.util.spec_from_file_location("e2e_server", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_browser_test_dataset_has_the_story_the_specs_rely_on(fresh_db_url, tmp_path):
    e2e = load_script()
    e2e.build_dataset(tmp_path)
    settings = load_settings(e2e.environment(fresh_db_url, tmp_path))
    e2e.seed(settings)
    factory = make_session_factory(make_engine(fresh_db_url))
    with factory() as db:
        assert sorted(role for (role,) in db.execute(select(User.role))) == ["admin", "member", "viewer"]
        kinds = sorted(kind for (kind,) in db.execute(select(Run.kind)))
        assert kinds == ["eval", "research"]
        eval_run = db.scalar(select(Run).where(Run.kind == "eval"))
        paper = db.scalar(select(Paper).where(Paper.source_id == "MED:3"))
        screening = db.scalar(select(Screening).where(Screening.run_id == eval_run.id, Screening.paper_id == paper.id))
        assert (screening.tier, screening.decision) == ("jev", "exclude")
        assert db.scalar(select(func.count()).select_from(Screening).where(Screening.run_id == eval_run.id)) == 12
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_e2e_server.py -v`
Expected: FAIL (`FileNotFoundError: scripts/e2e_server.py`).

- [ ] **Step 3: Write `scripts/e2e_server.py`**

```python
"""Serve the API, a worker and a small synthetic dataset for the browser tests. No network, no API keys.

Run from `web/` by Playwright (`python ../scripts/e2e_server.py`) with the project's virtualenv active.
The passwords below are test values for a throwaway local database.
"""

import shutil
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))  # web_fixtures and eval_helpers live with the tests

from research_agent.web.api.app import create_app  # noqa: E402
from research_agent.web.auth import create_user  # noqa: E402
from research_agent.web.cli import find_import_targets, run_imports  # noqa: E402
from research_agent.web.db.migrate import upgrade  # noqa: E402
from research_agent.web.db.session import make_engine, make_session_factory  # noqa: E402
from research_agent.web.settings import load_settings  # noqa: E402
from research_agent.web.worker import Worker  # noqa: E402

BASE = ROOT / ".web-dev" / "e2e"
PASSWORD = "e2e-test-password-1"  # keep in step with web/e2e/users.ts
USERS = {
    "viewer@example.org": ("Vera Viewer", "viewer"),
    "member@example.org": ("Mia Member", "member"),
    "admin@example.org": ("Ada Admin", "admin"),
}


def environment(database_url, base):
    return {
        "RESEARCH_WEB_DATABASE_URL": database_url,
        "RESEARCH_RUNS_DIR": str(Path(base) / "runs"),
        "RESEARCH_EVALS_DIR": str(Path(base) / "evals"),
        "RESEARCH_GOLD_DIR": str(Path(base) / "gold"),
        "RESEARCH_WEB_COOKIE_SECURE": "false",
        "RESEARCH_WEB_ALLOW_DEMO": "true",
        "RESEARCH_WEB_PROGRESS_POLL_SECONDS": "0.2",
    }


def build_dataset(base):
    """A demo research run and a toy eval set (paper MED:3 is in the SR and dropped by Jev)."""
    from web_fixtures import make_demo_run, make_eval_run

    base = Path(base)
    make_demo_run(base / "runs" / "demo")
    make_eval_run(base)  # writes base/evals/toy and base/gold/toy.json


def seed(settings):
    upgrade(settings.database_url)
    factory = make_session_factory(make_engine(settings.database_url))
    with factory() as db:
        for email, (name, role) in USERS.items():
            create_user(db, email=email, name=name, role=role, password=PASSWORD, min_password_length=settings.min_password_length)
        db.commit()
    if run_imports(settings, find_import_targets(settings)) != 0:
        raise SystemExit("importing the browser test dataset failed")


def main():
    import pgserver
    import uvicorn

    if BASE.exists():
        shutil.rmtree(BASE)
    BASE.mkdir(parents=True)
    build_dataset(BASE)
    server = pgserver.get_server(BASE / "pg", cleanup_mode="stop")
    url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    settings = load_settings(environment(url, BASE))
    seed(settings)
    stop = threading.Event()
    threading.Thread(target=Worker(settings).run_forever, kwargs={"stop": stop.is_set}, daemon=True, name="e2e-worker").start()
    try:
        uvicorn.run(create_app(settings), host="127.0.0.1", port=8000, log_level="warning")
    finally:
        stop.set()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify the seed test passes**

Run: `pytest tests/test_web_e2e_server.py -v`
Expected: 1 passed. If `run_imports` returns a non-zero code, run it by hand with `research-web import --all` against a scratch database and read the `FAILED` line.

- [ ] **Step 5: Configure Playwright**

In `web/vite.config.ts` add a `preview` block next to `server` (the browser tests use the built app):

```ts
  preview: {
    port: 4173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
```

Append `e2e/.auth` to `web/.gitignore` and `.web-dev/` to the repository `.gitignore` if it is not there yet.

`web/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: "http://127.0.0.1:4173", trace: "retain-on-failure" },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    { name: "chromium", use: { ...devices["Desktop Chrome"] }, dependencies: ["setup"], testIgnore: /auth\.setup\.ts/ },
  ],
  webServer: [
    { command: "python ../scripts/e2e_server.py", url: "http://127.0.0.1:8000/api/v1/health", timeout: 180_000, reuseExistingServer: !process.env.CI },
    { command: "npm run build && npm run preview -- --strictPort", url: "http://127.0.0.1:4173", timeout: 120_000, reuseExistingServer: !process.env.CI },
  ],
});
```

`web/e2e/users.ts`:

```ts
export const PASSWORD = "e2e-test-password-1"; // keep in step with scripts/e2e_server.py
export const ROLES = ["viewer", "member", "admin"] as const;
export type Role = (typeof ROLES)[number];
export const EMAIL: Record<Role, string> = { viewer: "viewer@example.org", member: "member@example.org", admin: "admin@example.org" };
export const auth = (role: Role) => `e2e/.auth/${role}.json`;
```

`web/e2e/auth.setup.ts`:

```ts
import { expect, test as setup } from "@playwright/test";

import { auth, EMAIL, PASSWORD, ROLES } from "./users";

for (const role of ROLES) {
  setup(`sign in as ${role}`, async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Email").fill(EMAIL[role]);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await page.context().storageState({ path: auth(role) });
  });
}
```

- [ ] **Step 6: Write the browser flows**

`web/e2e/flows.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

import { auth, EMAIL, PASSWORD } from "./users";

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a wrong password shows an error and stays on the sign-in page", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await page.getByLabel("Email").fill(EMAIL.viewer);
    await page.getByLabel("Password").fill("not the password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });
});

test.describe("viewer", () => {
  test.use({ storageState: auth("viewer") });

  test("cannot see Users or the start form", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Papers" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
    await page.goto("/users");
    await expect(page.getByRole("heading", { name: "Not allowed" })).toBeVisible();
    await page.goto("/runs");
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("button", { name: "Start run" })).toHaveCount(0);
  });

  test("the paper the screen dropped: filter, open, read the story, all from the keyboard", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await page.getByRole("button", { name: "Dropped" }).click();
    await page.getByRole("button", { name: "In the SR" }).click();
    const row = page.getByRole("row", { name: /MED:3/ });
    await expect(row).toBeVisible();
    const opener = row.getByRole("button").first();
    await opener.focus();
    await page.keyboard.press("Enter");
    const drawer = page.getByRole("complementary", { name: "Paper details" });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("heading").first()).toBeFocused();
    await expect(drawer.getByText("0.03")).toBeVisible();
    await expect(drawer.getByText(/Auto-drop needs/)).toBeVisible();
    await expect(drawer.getByText(/Included by the systematic review/)).toBeVisible();
    await expect(page).toHaveURL(/paper=/);
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(opener).toBeFocused();
  });

  test("the URL is the view: reloading keeps the filters and the open paper", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await page.getByRole("button", { name: "Only escalated" }).click();
    await page.reload();
    await expect(page.getByRole("button", { name: "Only escalated" })).toHaveAttribute("aria-pressed", "true");
  });

  test("System map: a stage is measured only with a measurement", async ({ page }) => {
    await page.goto("/system");
    await expect(page.getByRole("button", { name: /^Search/ })).toHaveAttribute("data-status", "measured");
    await expect(page.getByRole("button", { name: /^Rank/ })).toHaveAttribute("data-status", "unmeasured");
    await page.getByRole("button", { name: /^Rank/ }).click();
    await expect(page.getByRole("complementary", { name: "About Rank" })).toBeVisible();
    await expect(page).toHaveURL(/stage=rank/);
  });

  test("Evals: the threshold grid outlines the shipped default", async ({ page }) => {
    await page.goto("/evals");
    await expect(page.getByRole("region", { name: "Summary" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Threshold grid" })).toBeVisible();
    await expect(page.locator("table[aria-label='Threshold grid'] td.is-default")).toHaveCount(1);
    await expect(page.getByRole("table", { name: "Recall by strategy" })).toContainText("cascade");
  });
});

test.describe("member", () => {
  test.use({ storageState: auth("member") });

  test("starts a demo run, follows it to done and reads its papers", async ({ page }) => {
    test.setTimeout(150_000);
    await page.goto("/runs");
    await page.getByLabel("Field").selectOption({ index: 1 });
    await page.getByLabel("Papers to screen").fill("3");
    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByRole("status", { name: "Run progress" })).toContainText("done", { timeout: 120_000 });
    const row = page.locator("table.runs tbody tr").filter({ hasText: "research" }).filter({ has: page.locator("td", { hasText: /^3$/ }) });
    await row.getByRole("link", { name: /See papers/ }).click();
    await expect(page.locator("table.papers tbody tr")).toHaveCount(3);
  });
});

test.describe("admin", () => {
  test.use({ storageState: auth("admin") });

  test("invites a user who can then sign in", async ({ page }) => {
    await page.goto("/users");
    await page.getByLabel("Email").fill("nina@example.org");
    await page.getByLabel("Name").fill("Nina New");
    await page.getByLabel("Role", { exact: true }).selectOption("viewer");
    await page.getByLabel("Initial password").fill(PASSWORD);
    await page.getByRole("button", { name: "Invite" }).click();
    await expect(page.getByRole("cell", { name: "nina@example.org" })).toBeVisible();

    await page.context().clearCookies();
    await page.goto("/");
    await page.getByLabel("Email").fill("nina@example.org");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Users" })).toHaveCount(0);
  });
});
```

`web/e2e/a11y.spec.ts`:

```ts
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { auth } from "./users";

async function audit(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const found = results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
  expect(found, "accessibility violations").toEqual([]);
}

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test("sign-in page", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await audit(page);
  });
});

test.describe("viewer", () => {
  test.use({ storageState: auth("viewer") });

  test("papers table with the pipeline strip", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await expect(page.locator("table.papers tbody tr").first()).toBeVisible();
    await audit(page);
  });

  test("paper drawer open", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await page.locator("[data-open-paper]").first().click();
    await expect(page.getByRole("complementary", { name: "Paper details" })).toBeVisible();
    await audit(page);
  });

  test("stage panel open", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await page.getByRole("button", { name: /^Screen/ }).click();
    await expect(page.getByRole("complementary", { name: "About Screen" })).toBeVisible();
    await audit(page);
  });

  test("evals", async ({ page }) => {
    await page.goto("/evals");
    await expect(page.getByRole("table", { name: "Threshold grid" })).toBeVisible();
    await audit(page);
  });

  test("system map with a panel", async ({ page }) => {
    await page.goto("/system?stage=reviewers");
    await expect(page.getByRole("complementary", { name: "About Reviewers A and B" })).toBeVisible();
    await audit(page);
  });
});

test.describe("member", () => {
  test.use({ storageState: auth("member") });
  test("runs with the start form", async ({ page }) => {
    await page.goto("/runs");
    await expect(page.getByRole("button", { name: "Start run" })).toBeVisible();
    await audit(page);
  });
});

test.describe("admin", () => {
  test.use({ storageState: auth("admin") });
  test("users", async ({ page }) => {
    await page.goto("/users");
    await expect(page.getByRole("heading", { name: "Users" })).toBeVisible();
    await audit(page);
  });
});
```

- [ ] **Step 7: Install the browser and run**

Run (from `web/`, virtualenv active): `npx playwright install chromium && npm run e2e`
Expected: the setup project passes three sign-ins, then all flows and audits pass. The first run builds the app and seeds the database (about a minute).

If an accessibility test fails it prints the rule id and the selector. Fix the cause: colour contrast is fixed by changing a token in `styles.css` (never by removing a rule or disabling the test); a missing name or label is fixed in the component. If a flow fails on a wrong assumption about the toy data (for example the source id of the dropped paper), read the drawer in `npx playwright test --ui`, then fix the test **and** `test_the_browser_test_dataset_has_the_story_the_specs_rely_on` together, so the seed test keeps guarding the assumption.

- [ ] **Step 8: Commit**

```bash
ruff format src tests scripts && ruff check . && pytest -q && git add -A
git commit -m "Add browser end-to-end and accessibility tests on a synthetic dataset" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 14: CI, real-data check and documentation

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `tests/test_web_deploy.py`, `docs/web-app.md`, `docs/deployment.md`, `CLAUDE.md`, `README.md`

- [ ] **Step 1: Write the failing CI test**

Append to `tests/test_web_deploy.py`:

```python
CI = ROOT / ".github" / "workflows" / "ci.yml"


def test_ci_runs_every_check_and_needs_no_secrets():
    text = CI.read_text()
    workflow = yaml.safe_load(text)
    assert set(workflow["jobs"]) == {"python", "web", "e2e", "docker"}
    assert "secrets." not in text, "no check may need an API key"
    assert "pip-audit" in text and "npm audit" in text
    web = " ".join(step.get("run", "") for step in workflow["jobs"]["web"]["steps"])
    for command in ("npm ci", "npm run gen:api", "git diff --exit-code src/api/schema.d.ts", "npm run typecheck", "npm run lint", "npm test", "npm run build"):
        assert command in web, command
    python = " ".join(step.get("run", "") for step in workflow["jobs"]["python"]["steps"])
    assert "ruff check ." in python and "pytest" in python
    docker = " ".join(step.get("run", "") for step in workflow["jobs"]["docker"]["steps"])
    assert "docker compose -f deploy/docker-compose.yml config" in docker and "deploy/Dockerfile.web" in docker
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_web_deploy.py -k ci_runs -v`
Expected: FAIL (`FileNotFoundError` for `ci.yml`).

- [ ] **Step 3: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -e '.[dev,live,ui,web,web-dev]' pip-audit
      - run: ruff check .
      - run: pytest -q
      - run: pip-audit

  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: pip install -e '.[web]'
      - name: Frontend checks
        working-directory: web
        run: |
          npm ci
          npm run gen:api
          git diff --exit-code src/api/schema.d.ts
          npm run typecheck
          npm run lint
          npm test
          npm run build
          npm audit --audit-level=high

  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: pip install -e '.[dev,live,ui,web,web-dev]'
      - name: Browser tests
        working-directory: web
        run: |
          npm ci
          npx playwright install --with-deps chromium
          npm run e2e
      - uses: actions/upload-artifact@v4
        if: failure()
        with:
          name: playwright-report
          path: web/playwright-report

  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Validate and build the images
        run: |
          cp deploy/.env.example deploy/.env && sed -i 's/^DB_PASSWORD=$/DB_PASSWORD=ci-only/' deploy/.env
          cp deploy/worker.env.example deploy/worker.env
          docker compose -f deploy/docker-compose.yml config > /dev/null
          docker build -f deploy/Dockerfile -t research-agent-api .
          docker build -f deploy/Dockerfile.web -t research-agent-web .
```

(The compose file reads `worker.env` for the worker and `${DB_PASSWORD:?…}`; the copies above exist only inside the CI job. Docker is available on GitHub-hosted runners, so this is the first place the deployment files are actually built.)

- [ ] **Step 4: Run and commit the CI file**

Run: `pytest tests/test_web_deploy.py -q`
Expected: pass.

```bash
git add -A
git commit -m "Add the CI workflow: lint, tests, type and API-type drift checks, browser tests, image builds" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Check the real data in the browser**

The real runs and evals are git-ignored, so this is a manual check. In one terminal (the password comes from the environment so it never appears on a command line):

```bash
export RESEARCH_WEB_ADMIN_PASSWORD='choose-a-long-passphrase'
research-web dev --import-all --with-worker --allow-demo --admin-email you@example.org --admin-name "Your Name"
```

In a second terminal: `cd web && npm run dev`, then open `http://127.0.0.1:5173` and sign in. Check, and write down anything that differs:

1. **Papers** with the `mlffrct-2024` eval run: the strip reads Search and Screen `measured` with `recall 15/16`, Reviewers `caveat: one model family`, Rank `not measured`. The toolbar says 151 screened, 112 kept, 82 escalated, 16 in the SR.
2. Filters **Dropped** + **In the SR**: exactly one row, the ΔCT-FFR paper (`Change in CT-Derived FFR Across the Lesion Improve the Diagnostic Performance`), topic match `0.06`, badge `escalated`, decision `drop` by `LLM`, found by `lookup`. Open it: the timeline says Jev was not confident so the LLM decided, shows the auto-drop line, and the reviewers panel reads A `uncertain`, B `exclude`, adjudicator `uncertain`. As a member, Raw calls loads the exact prompt and response; as a viewer the tab is absent.
3. **Evals**: the numbers equal the report. Compare with the source of truth:

```bash
python3 -c "
import json
m = json.load(open('evals/mlffrct-2024/metrics.json'))
print('retrieval', m['retrieval_recall']['k'], m['retrieval_recall']['n'])
print('recommended', m['recommended']['min_confidence'], m['recommended']['exclude_min_confidence'])
row = next(r for r in m['sweep'] if (r['min_confidence'], r['exclude_min_confidence']) == (0.6, 0.9))
print('calls saved at the default pair', row['calls_saved'])
print('kappa', m['agreement']['verdict']['kappa'], 'same family', m['agreement']['same_family'])"
```

The Evals page must show the same retrieval recall, the same recommended pair (include ≥ 0.1, exclude ≥ 0.7, starred), the same calls saved in the outlined default cell, and the same kappa with the same-family flag. Pairs that lose an SR-included paper on either set are red and say so in words. Open the `aiffr-slr-2023` set from the picker as well: it is the holdout of the first, and has no holdout of its own, so its grid shows the "No holdout run" sentence.
4. **System map**: every stage box has its status in words; only measured ones are teal.
5. **Runs**: as a member, start a demo run with 3 papers; it goes queued → running → done and its papers open from "See papers". Stop the worker (Ctrl-C the dev server), start another run and confirm it stays `queued` rather than failing.
6. **Users**: as the admin, invite a viewer, sign in as them in a private window, confirm no Users link and no Start form; deactivate them and confirm their next request is refused.
7. Keyboard only, no mouse: Tab to a paper title, Enter opens the drawer and moves focus into it, Escape closes it and returns focus to the title.

Any mismatch between a number on screen and `metrics.json` is a bug in `features/evals/metrics.ts` or the page, not in the report.

- [ ] **Step 6: Document**

In `docs/web-app.md` add a **Frontend** section (plain prose plus the commands): requirements (Node 20 or newer), `cd web && npm install`, `npm run dev` (proxy to `127.0.0.1:8000`), `npm test`, `npm run gen:api` (regenerates `src/api/schema.d.ts` from the running code; CI fails if it is stale, so run it after any API change and commit the result), `npm run e2e` (starts its own API, worker and synthetic data; needs `npx playwright install chromium` once), the screen map (Papers, Runs, Evals, System map, Users) with which roles see what, and the three rules the UI keeps (a stage is green only when measured; missing data is hatched and never a dash; state is never colour alone). In `docs/deployment.md` add a sentence that the Compose file now builds three images (api/worker, web) and that GitHub Actions is where they are first built, since the development machine has no Docker.

In `CLAUDE.md` under "Comenzi" add one line for the web UI: `cd web && npm run dev` (with `research-web dev --import-all --with-worker --allow-demo` running) and `npm run e2e`; and a principle line under "Principii": *UI: o etapă e verde doar dacă există o măsurătoare; date lipsă ≠ nu se aplică; starea nu se transmite doar prin culoare.* In `README.md` add a short "Web app" paragraph linking `docs/web-app.md` and `docs/deployment.md`.

- [ ] **Step 7: Final verification and commit**

Run from the repository root (virtualenv active):

```bash
ruff check . && pytest -q && (cd web && npm run gen:api && git diff --exit-code src/api/schema.d.ts && npm run typecheck && npm run lint && npm test && npm run build)
```

Expected: everything green and `git diff` prints nothing (the generated types are current).

```bash
git add -A
git commit -m "Document the web frontend and the real-data check" -m "Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Self-review against the spec

**Spec coverage (slice 1, frontend part)**
- Sign-in page, session restore, CSRF on state-changing requests, 401 handling, role-gated routes and nav → Tasks 1 to 3.
- Papers (home): run picker, counts, filter chips, pipeline strip with status in words and headline numbers from `/stages`, the specified columns, sorting, paging, URL state, stage panel → Tasks 4 to 6. Null vs `{"missing": true}` cells → Task 5 (`cells.tsx`). Paper drawer timeline with Abstract and Raw calls (members only), abstract rendered as text → Task 6.
- Runs: list with status chips, Start run (members, cap 1 to 12, demo checkbox, idempotency key), job progress polling, failed-run banner with the sanitized reason and Resume → Task 8.
- Evals: summary cards, recall dot-and-interval rows, threshold grid (default outlined, recommended starred, risky pairs red and in words), rejected-pick note, caveats; needs the holdout sweep → Tasks 7 and 9.
- System map with clickable stages and panel, status computed by the backend and only rendered here → Task 10. Users (admin) → Task 11.
- Security: same-origin proxy, CSP `'self'` only with tests that keep the app compatible, no inline styles or HTML injection, security headers at the edge, read-only unprivileged web container → Task 12.
- Testing: Vitest and Testing Library for the strip, cells (missing vs not applicable), drawer and every page; generated-types staleness check in CI; Playwright flows (sign in, Papers, drawer by keyboard, System map, Evals grid, start a run, invite); axe on every main page → Tasks 1 to 14.
- Success criteria: real data shows in Papers, Evals and System map and the numbers equal `metrics.json` (Task 14, Step 5); an admin can invite a member who can start a demo run (Task 13); CI green.

**Placeholder scan:** none. Task 14 Step 6 lists documentation sections by content rather than full prose, as in plans 1 and 2; every command and code block is complete.

**Consistency:** hook names and query keys (`useRuns`, `usePapers`, `keys.runs`, `PaperParams`) are defined in Task 4 and used unchanged in Tasks 5 to 11; `StagePanel` and `statusText` are defined in Tasks 5 and 6 and reused by the System map; `parseEval`, `formatRate`, `rowFor`, `samePair` are defined in Task 9 and used only there; fixtures (`runOut`, `paperRow`, `lostRow`, `drawerOut`, `STAGES`, `jobOut`, `fieldOut`, `evalDetail`, `userRows`) are added by the task that first needs them. The e2e credentials appear in two files (`scripts/e2e_server.py`, `web/e2e/users.ts`) with a comment in each.

**Known limits, stated up front:** after a page reload a run started from the Runs page shows only its list status, not live progress (the API deliberately has no "job of this run" lookup); the Evals grid colours risk only from the eval sets that were actually imported (no holdout imported, no holdout risk shown, and the page says so); polling every 2 seconds rather than a live stream; the Docker images are first built in CI because the development machine has no Docker; the login rate limit is per API process.

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

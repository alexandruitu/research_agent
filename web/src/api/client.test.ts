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

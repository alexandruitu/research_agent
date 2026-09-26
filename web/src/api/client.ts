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

/** Returns an unsubscribe function (typed `() => void` so it can be a useEffect cleanup). */
export const onUnauthorized = (listener: () => void): (() => void) => {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
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

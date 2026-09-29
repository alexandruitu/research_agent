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

type ErrorBody = { code?: string; message?: string; request_id?: string; fields?: { loc: string; message: string }[] };

function toApiError(status: number, statusText: string, data: unknown): ApiError {
  const body = (data ?? {}) as ErrorBody;
  if (status === 401) unauthorizedListeners.forEach((listener) => listener());
  return new ApiError(status, body.code ?? "error", body.message ?? (statusText || "Request failed"), body.request_id ?? "-", body.fields);
}

const parse = (text: string): unknown => {
  try {
    return text ? JSON.parse(text) : undefined;
  } catch {
    return undefined;
  }
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
  const data = parse(await response.text());
  if (!response.ok) throw toApiError(response.status, response.statusText, data);
  return data as T;
}

/**
 * POSTs one file as multipart (field `file`). XMLHttpRequest, because fetch cannot report upload progress;
 * cookies and the CSRF header as for `api`.
 */
export function uploadFile<T>(path: string, file: File, onProgress?: (fraction: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1${path}`);
    xhr.withCredentials = true;
    xhr.setRequestHeader("Accept", "application/json");
    if (csrfToken) xhr.setRequestHeader("X-CSRF-Token", csrfToken);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress?.(event.loaded / event.total);
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Could not reach the server.", "-"));
    xhr.onload = () => {
      const data = parse(xhr.responseText);
      if (xhr.status >= 200 && xhr.status < 300) resolve(data as T);
      else reject(toApiError(xhr.status, "", data));
    };
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export const api = {
  get: <T>(path: string, params?: Params) => request<T>("GET", path, { params }),
  post: <T>(path: string, options?: Options) => request<T>("POST", path, options),
  patch: <T>(path: string, options?: Options) => request<T>("PATCH", path, options),
  delete: <T = void>(path: string) => request<T>("DELETE", path),
};

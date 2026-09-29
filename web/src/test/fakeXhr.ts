import { vi } from "vitest";

export type FakeXhrResult = { status: number; body?: unknown; progress?: number[] };

/** Replaces XMLHttpRequest. Each send answers with the next result (or `respond(request)`). */
export function fakeXhr(respond: FakeXhrResult | ((request: FakeXhr) => FakeXhrResult)) {
  const sent: FakeXhr[] = [];
  class Xhr {
    method = ""; url = ""; headers: Record<string, string> = {}; body: unknown = null; withCredentials = false;
    status = 0; responseText = "";
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    open(method: string, url: string) { this.method = method; this.url = url; }
    setRequestHeader(name: string, value: string) { this.headers[name] = value; }
    send(body: unknown) {
      this.body = body;
      sent.push(this as unknown as FakeXhr);
      const result = typeof respond === "function" ? respond(this as unknown as FakeXhr) : respond;
      queueMicrotask(() => {
        for (const f of result.progress ?? []) this.upload.onprogress?.({ lengthComputable: true, loaded: f * 100, total: 100 });
        if (result.status === 0) return this.onerror?.();
        this.status = result.status;
        this.responseText = result.body === undefined ? "" : JSON.stringify(result.body);
        this.onload?.();
      });
    }
  }
  vi.stubGlobal("XMLHttpRequest", Xhr);
  return { sent };
}

export type FakeXhr = { method: string; url: string; headers: Record<string, string>; body: unknown; withCredentials: boolean };

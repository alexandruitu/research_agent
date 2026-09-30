import { QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../test/mockApi";
import { testQueryClient } from "../test/render";
import { exportUrl, keys, useLibrary, useSaveToLibrary } from "./hooks";

afterEach(() => vi.unstubAllGlobals());

const wrap = (client = testQueryClient()) => ({ client, wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> });

describe("library hooks", () => {
  it("send the list filters as query parameters", async () => {
    const { calls } = mockApi({ "GET /api/v1/library": { body: { items: [], total: 0, page: 1, page_size: 50 } } });
    const { wrapper } = wrap();
    const { result } = renderHook(() => useLibrary({ q: "plaque", status: "relevant", has_red_flags: true, page: 1 }), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const search = new URLSearchParams(calls[0]!.search);
    expect(search.get("q")).toBe("plaque");
    expect(search.get("status")).toBe("relevant");
    expect(search.get("has_red_flags")).toBe("true");
  });

  it("build the export link from the filters, without paging or empty values", () => {
    expect(exportUrl({ status: "relevant", q: "", page: 3, page_size: 50, tag: undefined }, "bibtex")).toBe("/api/v1/library/export?format=bibtex&status=relevant");
  });

  it("refresh papers, drawers, the library and collections after a save", async () => {
    mockApi({ "POST /api/v1/library": { status: 201, body: { created: [], existing: [], items: [], collection: null } } });
    const { client, wrapper } = wrap();
    const spy = vi.spyOn(client, "invalidateQueries");
    const { result } = renderHook(() => useSaveToLibrary(), { wrapper });
    await result.current.mutateAsync({ run_id: "r", paper_ids: ["p"], collection_ids: [], tags: [], note: "", status: "to_read" });
    const invalidated = spy.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
    expect(invalidated).toEqual(expect.arrayContaining([JSON.stringify(keys.allLibrary), JSON.stringify(keys.allCollections), '["papers"]', '["paper"]']));
  });
});

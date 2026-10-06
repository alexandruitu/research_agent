import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { setItemStatus, setPaperLibrary } from "./optimistic";

const row = (id: string) => ({ paper: { id }, library: null }) as never;

describe("optimistic library updates", () => {
  it("patch paper pages but leave the group-count queries (same 'papers' prefix) alone", () => {
    const client = new QueryClient();
    client.setQueryData(["papers", "run-1", { page: 1 }], { items: [row("p1"), row("p2")], total: 2, page: 1, page_size: 25 });
    const groups = [{ key: "worth_a_look", label: "Worth a look", count: 2 }];
    client.setQueryData(["papers", "run-1", "groups", "quality", {}], groups);

    expect(() => setPaperLibrary(client, { p1: { item_id: "pending-p1", status: "to_read", collections: [] } })).not.toThrow();
    const page = client.getQueryData<{ items: { paper: { id: string }; library: unknown }[] }>(["papers", "run-1", { page: 1 }]);
    expect(page?.items[0].library).toEqual({ item_id: "pending-p1", status: "to_read", collections: [] });
    expect(page?.items[1].library).toBeNull();
    expect(client.getQueryData(["papers", "run-1", "groups", "quality", {}])).toBe(groups);

    expect(() => setItemStatus(client, "pending-p1", "read")).not.toThrow();
  });
});

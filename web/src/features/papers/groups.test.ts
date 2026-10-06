import { afterEach, describe, expect, it, vi } from "vitest";

import { groupIcon, groupName, readCollapsed, writeCollapsed } from "./groups";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("collapsed groups", () => {
  it("starts with 'Not relevant' collapsed in quality groups and nothing elsewhere", () => {
    expect([...readCollapsed("u1", "quality")]).toEqual(["not_relevant"]);
    expect(readCollapsed("u1", "year").size).toBe(0);
  });

  it("remembers the state per user and per grouping", () => {
    writeCollapsed("u1", "quality", new Set(["read_first"]));
    expect([...readCollapsed("u1", "quality")]).toEqual(["read_first"]);
    expect([...readCollapsed("u2", "quality")]).toEqual(["not_relevant"]);
    expect(readCollapsed("u1", "source").size).toBe(0);
  });

  it("falls back to the defaults when storage is blocked or holds junk, without throwing", () => {
    window.localStorage.setItem("papers.collapsed.u1.quality", "{not json");
    expect([...readCollapsed("u1", "quality")]).toEqual(["not_relevant"]);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    expect(() => writeCollapsed("u1", "quality", new Set())).not.toThrow();
    expect([...readCollapsed("u1", "quality")]).toEqual(["not_relevant"]);
  });
});

describe("group names", () => {
  it("names groups in words, with an icon only as decoration", () => {
    expect(groupName("quality", "read_first", "Read first")).toBe("Read first");
    expect(groupIcon("quality", "has_problems")).toBe("⚑");
    expect(groupName("decided_by", "kept", "Kept by screening")).toBe("Kept by screening");
    expect(groupName("decided_by", "topic_match", "topic_match")).toMatch(/^Dropped by /);
    expect(groupName("year", "2021", "2021")).toBe("2021");
  });
});

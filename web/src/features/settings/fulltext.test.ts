import { describe, expect, it } from "vitest";

import { enabledOrder, FULLTEXT_SOURCES, moveResolver, resolverList } from "./fulltext";

describe("full-text resolver order", () => {
  it("lists all nine resolvers, the enabled ones first in their saved order", () => {
    const list = resolverList(["unpaywall", "pmc_oa"]);
    expect(list).toHaveLength(9);
    expect(list.slice(0, 3)).toEqual([{ key: "unpaywall", on: true }, { key: "pmc_oa", on: true }, { key: "europepmc", on: false }]);
    expect(list.at(-1)).toEqual({ key: "upload", on: false });
    expect(FULLTEXT_SOURCES.every((r) => r.licence.length > 0)).toBe(true);
  });

  it("moves one place up or down and never past the ends", () => {
    const list = resolverList(["pmc_oa", "upload"]);
    expect(enabledOrder(moveResolver(list, 1, -1))).toEqual(["upload", "pmc_oa"]);
    expect(moveResolver(list, 0, -1)).toBe(list);
    expect(moveResolver(list, 8, 1)).toBe(list);
  });

  it("toggling keeps a resolver's place; only enabled resolvers are sent", () => {
    const list = resolverList(["pmc_oa", "upload"]).map((e) => (e.key === "core" ? { ...e, on: true } : e));
    expect(enabledOrder(list)).toEqual(["pmc_oa", "upload", "core"]);
  });
});

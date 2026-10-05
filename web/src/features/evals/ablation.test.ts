import { describe, expect, it } from "vitest";

import { ablationMetrics } from "../../test/fixtures";
import { parseAblation } from "./ablation";

describe("parseAblation", () => {
  it("reads sizes in order, subsets with names, and the summary", () => {
    const view = parseAblation(ablationMetrics());
    expect(view.sizes.map((s) => s.size)).toEqual([1, 2, 3]);
    expect(view.sizes[0]).toMatchObject({ verdictChanged: 0.4, redFlagsMissed: 0.6, costCalls: 10 });
    expect(view.subsets[1]).toMatchObject({ subset: "methodologist+statistician", size: 2, scoreDelta: 3.1, calls: 20 });
    expect(view.summary?.sentence).toMatch(/Going from 2 to 3/);
    expect(view.papers).toBe(10);
  });

  it("survives a missing section", () => {
    expect(parseAblation({})).toMatchObject({ sizes: [], subsets: [], summary: null, papers: 0 });
  });
});

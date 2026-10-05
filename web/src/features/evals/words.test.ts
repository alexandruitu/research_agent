import { describe, expect, it } from "vitest";

import { familyOf, kappaWords, pct, ratioText, scoreOf } from "./words";

describe("words", () => {
  it.each([
    [-0.1, "worse than chance"], [0.1, "slight"], [0.3, "fair"], [0.42, "moderate"], [0.7, "substantial"], [0.9, "almost perfect"], [null, "not measured"],
  ])("kappa %s reads %s", (k, words) => expect(kappaWords(k)).toBe(words));

  it("formats shares as whole percentages and says when missing", () => {
    expect(pct(0.734)).toBe("73%");
    expect(pct(null)).toBe("n/a");
  });

  it("ratio text gives the counts and the share", () => {
    expect(ratioText({ k: 8, n: 10, value: 0.8, ci: [0.5, 0.95], reason: null })).toBe("80% (8 of 10)");
    expect(ratioText({ k: 0, n: 0, value: null, ci: null, reason: "no papers" })).toBe("n/a (no papers)");
    expect(ratioText(null)).toBe("n/a");
  });

  it("groups kinds into compare families", () => {
    expect(familyOf("human")).toBe("panel");
    expect(familyOf("panel")).toBe("panel");
    expect(familyOf("ablation")).toBe("ablation");
    expect(familyOf(undefined)).toBe("screening");
  });

  it("reads a kappa from a number or a cohen object", () => {
    expect(scoreOf(0.5)).toBe(0.5);
    expect(scoreOf({ kappa: 0.4 })).toBe(0.4);
    expect(scoreOf({ kappa: null })).toBeNull();
    expect(scoreOf(undefined)).toBeNull();
  });
});

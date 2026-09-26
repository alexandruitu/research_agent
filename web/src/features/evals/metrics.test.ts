import { describe, expect, it } from "vitest";

import { evalMetrics } from "../../test/fixtures";
import { formatRate, parseEval, rowFor } from "./metrics";

describe("parseEval", () => {
  it("reads the parts of metrics.json the page shows", () => {
    const view = parseEval(evalMetrics());
    expect(view.gold.name).toBe("mlffrct-2024");
    expect(view.retrievalRecall).toMatchObject({ k: 15, n: 16 });
    expect(view.strategies.map((s) => s.name)).toEqual(["llm_only", "jev_only", "cascade"]);
    expect(view.defaultPair).toEqual({ include: 0.6, exclude: 0.9 });
    expect(view.recommended).toEqual({ include: 0.1, exclude: 0.7 });
    expect(view.holdout?.gold).toBe("aiffr-slr-2023");
    expect(view.rejected?.pair).toEqual({ include: 0.1, exclude: 0.5 });
    expect(view.agreement?.kappa).toBe(0.945);
    expect(view.agreement?.sameFamily).toBe(true);
    expect(view.warnings).toHaveLength(1);
  });

  it("copes with a report that has no holdout, no agreement and no recommendation", () => {
    const view = parseEval({ ...evalMetrics(), holdout_sweep: null, holdout: null, rejected_on_holdout: null, agreement: null, recommended: null });
    expect(view.holdout).toBeNull();
    expect(view.rejected).toBeNull();
    expect(view.agreement).toBeNull();
    expect(view.recommended).toBeNull();
  });

  it("does not crash on an unexpected shape, it just shows less", () => {
    const view = parseEval({});
    expect(view.strategies).toEqual([]);
    expect(view.sweep).toEqual([]);
    expect(view.retrievalRecall).toBeNull();
  });
});

describe("formatRate", () => {
  it("shows k/n with the interval, and the reason when it is undefined", () => {
    expect(formatRate({ k: 15, n: 16, value: 15 / 16, ci: [0.72, 0.99], reason: null })).toBe("15/16 (95% CI 0.72–0.99)");
    expect(formatRate({ k: 0, n: 0, value: null, ci: null, reason: "zero denominator" })).toBe("n/a (zero denominator)");
    expect(formatRate(null)).toBe("n/a");
  });
});

describe("rowFor", () => {
  it("finds the sweep row for a pair, or undefined", () => {
    const rows = parseEval(evalMetrics()).sweep;
    expect(rowFor(rows, { include: 0.6, exclude: 0.9 })?.callsSaved).toBe(69);
    expect(rowFor(rows, { include: 0.9, exclude: 0.5 })).toBeUndefined();
  });
});

import { describe, expect, it } from "vitest";

import { bands, fromEvals, validateScreening, widthClass } from "./screening";

const ok = { keep_min: 0.8, include_fail_max: 0.05, exclude_hit_min: 0.95, exclude_clear_max: 0.2 };

describe("screening thresholds", () => {
  it("translates the Evals pair exactly for inclusion criteria (the Jev confidence rule)", () => {
    expect(fromEvals({ include: 0.6, exclude: 0.9 })).toEqual({ keep_min: 0.8, include_fail_max: 0.05 });
    expect(fromEvals({ include: 0.1, exclude: 0.7 })).toEqual({ keep_min: 0.55, include_fail_max: 0.15 });
  });

  it("explains invalid bands in words", () => {
    expect(validateScreening(ok)).toEqual([]);
    expect(validateScreening({ ...ok, include_fail_max: 0.9 })).toEqual(["Inclusion criteria: “Drop at or below” must be lower than “Keep from”."]);
    expect(validateScreening({ ...ok, exclude_clear_max: 0.96 })).toEqual(["Exclusion criteria: “Clear at or below” must be lower than “Drop from”."]);
    expect(validateScreening({ ...ok, keep_min: 1.2 })).toEqual(["Every threshold is a probability from 0 to 1."]);
    expect(validateScreening({ ...ok, keep_min: Number.NaN })).toEqual(["Every threshold is a probability from 0 to 1."]);
  });

  it("splits the 0–1 scale into three bands in 5% steps that always sum to 100", () => {
    expect(bands(0.05, 0.8)).toEqual({ low: 5, middle: 75, high: 20 });
    expect(bands(0.2, 0.95)).toEqual({ low: 20, middle: 75, high: 5 });
    expect(bands(0.5, 0.5)).toEqual({ low: 50, middle: 0, high: 50 });
    expect(widthClass(35)).toBe("w-35");
  });
});

import { describe, expect, it } from "vitest";

import { reviewerOut } from "../../test/fixtures";
import { diffReviewers } from "./reviewerDiff";

const item = (key: string, text: string, pass_if = "yes") => ({ key, text, weight: 1, source: null, pass_if, red_flag_if: null });

describe("reviewer version diff", () => {
  it("names added, removed and changed items and changed settings", () => {
    const base = reviewerOut().current;
    const before = { ...base, model: null, items: [item("m1", "Split by patient."), item("m2", "External test set.")] };
    const after = { ...base, model: "anthropic:x", items: [item("m1", "Split by patient.", "no"), item("m3", "Code is shared.")] };
    expect(diffReviewers(before, after)).toEqual([
      { kind: "changed", text: "Model: worker default → anthropic:x" },
      { kind: "changed", text: "m1: Split by patient. (weight 1, passes on no)" },
      { kind: "added", text: "m3: Code is shared. (weight 1, passes on yes)" },
      { kind: "removed", text: "m2: External test set. (weight 1, passes on yes)" },
    ]);
  });

  it("is empty for identical versions", () => {
    const v = reviewerOut().current;
    expect(diffReviewers(v, v)).toEqual([]);
  });
});

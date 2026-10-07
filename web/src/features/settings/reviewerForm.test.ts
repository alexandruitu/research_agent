import { describe, expect, it } from "vitest";

import { reviewerOut } from "../../test/fixtures";
import { emptyItem, firstSentence, formFromContent, joinSource, moveItem, preview, splitSource, toBody, validateReviewer } from "./reviewerForm";

describe("reviewer form", () => {
  it("splits and joins checklist sources", () => {
    expect(splitSource("CLAIM 2020 #21")).toEqual({ family: "CLAIM", ref: "2020 #21" });
    expect(splitSource("TRIPOD+AI 12")).toEqual({ family: "TRIPOD+AI", ref: "12" });
    expect(splitSource(null)).toEqual({ family: "none", ref: "" });
    expect(splitSource("STARD 3")).toEqual({ family: "other", ref: "STARD 3" });
    expect(joinSource("CLAIM", " 21 ")).toBe("CLAIM 21");
    expect(joinSource("TRIPOD+AI", "")).toBe("TRIPOD+AI");
    expect(joinSource("other", "")).toBeNull();
    expect(joinSource("none", "x")).toBeNull();
  });

  it("round-trips a saved version into a request body, dropping empty items", () => {
    const form = formFromContent(reviewerOut().current);
    form.items.push(emptyItem());
    expect(toBody(form, " why ")).toEqual({
      name: "Methodologist", perspective: reviewerOut().current.perspective, model: "anthropic:claude-sonnet-5", note: "why",
      items: [
        { key: "m1", text: "Data were split at patient level, not image level.", weight: 2, source: "CLAIM 21", pass_if: "yes", red_flag_if: "no", flag_text: "Data not split by patient" },
        { key: "m2", text: "The model was validated on an external dataset.", weight: 3, source: "TRIPOD+AI 12", pass_if: "yes", red_flag_if: null, flag_text: null },
      ],
    });
  });

  it("validates in plain words", () => {
    const form = { name: "", perspective: "short", model: null, items: [{ ...emptyItem(), text: "ab" }] };
    expect(validateReviewer(form)).toEqual(["Give the reviewer a name.", "Describe the perspective in at least 10 characters.", "Item 1 is too short."]);
    expect(validateReviewer({ ...form, name: "X", perspective: "A long enough perspective", items: [] })).toEqual(["Add at least one checklist item."]);
    expect(validateReviewer({ ...form, name: "X", perspective: "A long enough perspective", items: [{ ...emptyItem(), text: "abc", flagText: "x".repeat(201) }] }))
      .toEqual(["The red-flag wording of item 1 is longer than 200 characters."]);
  });

  it("previews only the perspective and each item's key and text", () => {
    const form = formFromContent(reviewerOut().current);
    form.items.push({ ...emptyItem(), text: "New question?" });
    expect(preview(form).items).toEqual([
      { key: "m1", text: "Data were split at patient level, not image level." },
      { key: "m2", text: "The model was validated on an external dataset." },
      { key: "new 3", text: "New question?" },
    ]);
  });

  it("moves items and finds the first sentence", () => {
    expect(moveItem(["a", "b", "c"], 0, 1)).toEqual(["b", "a", "c"]);
    expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
    expect(firstSentence("Judges design. Also leakage.")).toBe("Judges design.");
    expect(firstSentence("No period")).toBe("No period");
  });
});

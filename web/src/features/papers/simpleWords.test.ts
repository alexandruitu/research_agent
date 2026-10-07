import { describe, expect, it } from "vitest";

import { lostRow, paperRow } from "../../test/fixtures";
import { nextAction, plainWhy } from "./simpleWords";

const MECHANICS = /Jev|LLM|escalat|threshold|p 0\./;

describe("Simple view words", () => {
  it("says why in plain words, without tiers, models or thresholds", () => {
    for (const row of [paperRow(), lostRow(), paperRow({ red_flag_count: 1, red_flags: ["No external validation"] })]) {
      expect(plainWhy(row)).not.toMatch(MECHANICS);
    }
  });
  it("names the red flag problem and asks to check it", () => {
    const row = paperRow({ red_flag_count: 2, red_flags: ["No external validation", "Data not split by patient"] });
    expect(plainWhy(row)).toBe("Matches your search, but the review found a problem: No external validation.");
    expect(nextAction(row)?.word).toBe("Check red flag");
  });
  it("asks for the full text when only the abstract was read", () => {
    const row = paperRow({ red_flag_count: 0, red_flags: [], text_source: "abstract", provisional: true });
    expect(plainWhy(row)).toContain("only the abstract was read");
    expect(nextAction(row)?.word).toBe("Upload full text");
  });
  it("says a paper with problems should not be relied on, before the abstract caveat", () => {
    expect(plainWhy(paperRow({ red_flag_count: 0, red_flags: [], group: "has_problems", text_source: "abstract" }))).toContain("advises against relying on it");
  });
  it("has no next action for a dropped paper and names the criterion", () => {
    const row = lostRow();
    expect(nextAction(row)).toBeNull();
    expect(plainWhy(row, { [row.screen.decided_by ?? "topic_match"]: "Uses deep learning." })).toMatch(/^Does not match your search/);
  });
  it("offers Save, then Read once saved", () => {
    const row = paperRow({ red_flag_count: 0, red_flags: [], text_source: "pmc_oa", provisional: false, group: "read_first", library: null });
    expect(nextAction(row)?.word).toBe("Save");
    expect(nextAction({ ...row, library: { item_id: "x", status: "to_read", collections: [] } })?.word).toBe("Read");
  });
});

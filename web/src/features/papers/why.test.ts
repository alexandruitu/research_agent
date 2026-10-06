import { describe, expect, it } from "vitest";

import { paperRow } from "../../test/fixtures";
import { criteriaSummary, criterionLines, whySentence } from "./why";

const cell = (kind: string, jev_p: number | null, llm: string | null = null, quote: string | null = null) => ({ kind, jev_p, llm, quote });
const kept = paperRow({
  screen: {
    tier: "jev", decision: "include", jev_decision: "include", llm_decision: null, criteria: {}, decided_by: null,
    cells: { i1: cell("include", 0.97), i2: cell("include", 0.91), e1: cell("exclude", 0.02), e2: cell("exclude", 0.1) },
  },
  reviews: null, score: 72, coverage: 0.3, red_flag_count: 1, text_source: "abstract", provisional: true, checklist_answered: 3, checklist_total: 10,
});
const dropped = paperRow({
  screen: {
    tier: "llm", decision: "exclude", jev_decision: "escalate", llm_decision: "exclude", criteria: {}, decided_by: "i2",
    cells: { i1: cell("include", 0.9, "yes"), i2: cell("include", 0.3, "no", "We used a random forest on clinical variables.") },
  },
  reviews: null,
});

describe("criteria summary", () => {
  it("counts the criteria a kept paper passes (an exclusion passes when it does not hold)", () => {
    expect(criterionLines(kept.screen).map((l) => l.state)).toEqual(["met", "met", "met", "met"]);
    expect(criteriaSummary(kept.screen)).toEqual({ icon: "✓", text: "4/4 met" });
  });
  it("names the criterion that dropped a paper", () => {
    expect(criteriaSummary(dropped.screen)).toEqual({ icon: "✕", text: "dropped by incl 2" });
  });
  it("counts unclear answers", () => {
    const screen = { ...kept.screen, cells: { i1: cell("include", null, "unclear"), i2: cell("include", null) } };
    expect(criteriaSummary(screen)).toEqual({ icon: "?", text: "2 unclear" });
  });
  it("says when a paper was never screened", () => {
    expect(criteriaSummary({ ...kept.screen, tier: "rule" }).text).toBe("not screened");
  });
});

describe("why sentence", () => {
  it("explains a kept paper with the panel's findings", () => {
    expect(whySentence(kept)).toBe("Kept: meets all 4 criteria; panel found 1 red flag; score provisional (3 of 10 checklist items answered); abstract only.");
  });
  it("names the red flags when the drawer knows them", () => {
    expect(whySentence(kept, { redFlags: ["No external validation."] })).toContain("panel found 1 red flag (no external validation)");
  });
  it("explains a dropped paper with the criterion text, who decided and the quote", () => {
    expect(whySentence(dropped, { texts: { i2: "Uses deep learning." } })).toBe(
      "Dropped: doesn't meet ‘Uses deep learning’ (LLM, quote: “We used a random forest on clinical variables.”).",
    );
  });
  it("names an exclusion criterion and Jev's probability", () => {
    const row = paperRow({ screen: { tier: "jev", decision: "exclude", jev_decision: "exclude", llm_decision: null, criteria: {}, decided_by: "e1", cells: { e1: cell("exclude", 0.98) } } });
    expect(whySentence(row)).toBe("Dropped: matches the exclusion excl 1 (Jev, p 0.98).");
  });
  it("clips long quotes in the table only", () => {
    const long = paperRow({ screen: { ...dropped.screen, cells: { i2: cell("include", 0.3, "no", "x".repeat(300)) } } });
    expect(whySentence(long)).toContain("…”");
    expect(whySentence(long, { maxQuote: Infinity })).toContain("x".repeat(300));
  });
  it("covers papers never screened and legacy A/B reviews", () => {
    expect(whySentence(paperRow({ screen: { ...kept.screen, tier: "rule" }, reviews: null }))).toBe("Not screened: no abstract was available.");
    expect(whySentence(paperRow())).toBe("Kept: meets the criterion; reviewers say include.");
  });
});

describe("drawer why", () => {
  it("is the same sentence, naming the red flags and the full text read", async () => {
    const { drawerOut, panelOut } = await import("../../test/fixtures");
    const { drawerWhy } = await import("./why");
    const drawer = drawerOut({ screening: { ...drawerOut().screening, tier: "jev", decision: "include", jev_decision: "include", llm_decision: null, criteria: [{ key: "topic_match", question: "", probability: 0.97, jev_version: "j" }] }, reviews: [], panel: panelOut() });
    expect(drawerWhy(drawer)).toBe("Kept: meets the criterion; panel found 1 red flag (data were split at patient level, not image level); full text read.");
  });
});

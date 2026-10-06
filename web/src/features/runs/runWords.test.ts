import { describe, expect, it } from "vitest";

import { canManageRun, coverageLine, runOption, formatSeconds, formatUsd, runLabel } from "./runWords";

const me = { id: "u1", email: "m@x", name: "M", role: "member", active: true };

describe("run words", () => {
  it("labels a run by name, else field and version", () => {
    expect(runLabel({ name: "Baseline", field_name: "F", field_version: 2 })).toBe("Baseline");
    expect(runLabel({ name: null, field_name: "F", field_version: 2 })).toBe("F · v2");
  });
  it("lets the creator or an admin manage, never a viewer or an imported run for members", () => {
    expect(canManageRun(me, { created_by: "u1" })).toBe(true);
    expect(canManageRun(me, { created_by: "u2" })).toBe(false);
    expect(canManageRun(me, { created_by: null })).toBe(false);
    expect(canManageRun({ ...me, role: "admin" }, { created_by: null })).toBe(true);
    expect(canManageRun({ ...me, role: "viewer" }, { created_by: "u1" })).toBe(false);
  });
  it("formats durations and costs in words", () => {
    expect(formatSeconds(null)).toBe("not recorded");
    expect(formatSeconds(42.4)).toBe("42 s");
    expect(formatSeconds(125)).toBe("2 min 5 s");
    expect(formatSeconds(3720)).toBe("1 h 2 min");
    expect(formatUsd(null)).toBe("no price");
    expect(formatUsd(0.004)).toBe("< $0.01");
    expect(formatUsd(1.234)).toBe("$1.23");
  });
});

describe("coverage line", () => {
  it("says what the run searched, skipped, capped and read", () => {
    expect(coverageLine({
      searched: ["europepmc", "openalex"], skipped: [{ source: "semantic_scholar", error_type: "x", reason: "rate limited (HTTP 429)", detail: "" }],
      max_papers: 12, full_text: 3, abstract_only: 7,
    })).toBe("Searched: Europe PMC, OpenAlex · Skipped: Semantic Scholar (rate limited) · Max papers: 12 · Text: 3 full text / 7 abstract only");
  });
  it("says what is unknown instead of showing zeros", () => {
    expect(coverageLine({ searched: [], skipped: null, max_papers: null, full_text: null, abstract_only: null }))
      .toBe("Searched: not recorded · Max papers: not recorded · Text: not reviewed by the panel");
    expect(coverageLine({ searched: ["europepmc"], skipped: [], max_papers: 5, full_text: null, abstract_only: null })).toContain("Skipped: none");
    expect(coverageLine(null)).toBeNull();
  });
});

describe("run picker options", () => {
  it("use the short name, clip long labels and keep the full text with the topic for hover", () => {
    expect(runOption({ name: "Baseline", field_name: "F", field_version: 1, topic: "deep learning CT-FFR" }, ["12 papers"])).toEqual({ text: "Baseline · 12 papers", title: "Baseline · 12 papers — deep learning CT-FFR" });
    const long = runOption({ name: null, field_name: "x".repeat(100), field_version: null, topic: "" });
    expect(long.text).toHaveLength(72);
    expect(long.text.endsWith("…")).toBe(true);
    expect(long.title).toBe("x".repeat(100));
  });
});

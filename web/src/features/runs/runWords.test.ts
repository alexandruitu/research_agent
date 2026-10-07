import { describe, expect, it } from "vitest";

import { canManageRun, coverageLine, newestFirst, runIdentity, runOption, formatSeconds, formatUsd, runLabel } from "./runWords";

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

const base = { name: null, field_name: "ML CT-FFR", field_version: 3, topic: "deep learning CT-FFR", created_at: "2026-10-06T11:25:00", status: "done" };

describe("run picker options", () => {
  it("say short name · field vN · date · status, with the topic for hover", () => {
    expect(runIdentity({ ...base, name: "Baseline" })).toBe("Baseline · ML CT-FFR v3 · 6 Oct, 11:25 · done");
    expect(runOption({ ...base, name: "Baseline" }, ["12 papers"])).toEqual({
      text: "Baseline · ML CT-FFR v3 · 6 Oct, 11:25 · done · 12 papers",
      title: "Baseline · ML CT-FFR v3 · 6 Oct, 11:25 · done · 12 papers — deep learning CT-FFR",
    });
  });
  it("fall back to the topic, clipped, and mark failed or cancelled runs in words", () => {
    const run = { ...base, topic: "x".repeat(60), status: "failed" };
    expect(runIdentity(run)).toBe(`${"x".repeat(39)}… · ML CT-FFR v3 · 6 Oct, 11:25 · ! failed`);
    expect(runIdentity({ ...base, status: "cancelled" })).toMatch(/· ⊘ cancelled$/);
  });
  it("do not repeat a topic the field is named after, and clip long field names", () => {
    expect(runIdentity({ ...base, field_name: "deep learning CT-FFR" })).toBe("deep learning CT-FFR v3 · 6 Oct, 11:25 · done");
    expect(runIdentity({ ...base, name: null, topic: "", field_name: "f".repeat(50) })).toBe(`${"f".repeat(31)}… v3 · 6 Oct, 11:25 · done`);
  });
  it("sort most recent first", () => {
    const runs = [{ id: "a", created_at: "2026-10-01T00:00:00Z" }, { id: "b", created_at: "2026-10-06T00:00:00Z" }];
    expect(newestFirst(runs).map((r) => r.id)).toEqual(["b", "a"]);
  });
});

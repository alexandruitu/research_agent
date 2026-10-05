import { describe, expect, it } from "vitest";

import { humanSection, panelMetrics } from "../../test/fixtures";
import { parsePanel } from "./panel";

describe("parsePanel", () => {
  it("reads agreement with raw agreement and prevalence, editor and reviewers with names", () => {
    const view = parsePanel(panelMetrics());
    expect(view.n).toBe(10);
    expect(view.fleiss).toEqual({ kappa: 0.42, agreement: 0.73, prevalence: 0.8, raters: 3, reason: null });
    expect(view.editor?.k).toBe(9);
    expect(view.reviewers.map((r) => r.name)).toEqual(["Methodologist", "Statistician", "Clinician"]);
    expect(view.textSources).toEqual([{ source: "fulltext", count: 6 }, { source: "abstract", count: 4 }]);
    expect(view.pairwise).toEqual([{ a: "Methodologist", b: "Statistician", kappa: 0.5, agreement: 0.8, prevalence: 0.7 }]);
  });

  it("keeps items worst-first with reviewer names and reword flags", () => {
    const { items } = parsePanel(panelMetrics());
    expect(items[0]).toMatchObject({ text: "Was the test set split by patient?", reword: true, reviewers: ["Statistician"], unanswered: 0.8 });
    expect(items[1]).toMatchObject({ kappa: 0.8, reword: false });
  });

  it("builds coverage rows with item text, full text and abstract", () => {
    const rows = parsePanel(panelMetrics()).coverage;
    const stat = rows.find((r) => r.item === "s1")!;
    expect(stat).toMatchObject({ reviewer: "Statistician", text: "Was the test set split by patient?" });
    expect(stat.fulltext?.k).toBe(2);
    expect(stat.abstract?.n).toBe(4);
  });

  it("reads dispersion, AUC and families", () => {
    const view = parsePanel(panelMetrics());
    expect(view.dispersion[0]).toMatchObject({ paperId: "MED:35097009", range: 50 });
    expect(view.auc).toMatchObject({ value: 0.71, ci: [0.48, 0.94], nPos: 4, nNeg: 6 });
    expect(view.families).toMatchObject({ single: true, provider: "anthropic" });
    expect(view.human).toBeNull();
  });

  it("reads a human section", () => {
    const human = parsePanel(panelMetrics({ human: humanSection() })).human!;
    expect(human.raters).toBe(2);
    expect(human.panelAccuracy?.k).toBe(30);
    expect(human.panelKappa).toBe(0.48);
    expect(human.perReviewer[0]).toMatchObject({ name: "Methodologist", kappa: 0.55 });
    expect(human.perItem[0]).toMatchObject({ reviewer: "Statistician", kappa: 0.1 });
    expect(human.spearman).toEqual({ rho: 0.8, n: 5, reason: null });
  });

  it("survives an empty metrics object", () => {
    const view = parsePanel({});
    expect(view.n).toBe(0);
    expect(view.fleiss).toBeNull();
    expect(view.items).toEqual([]);
    expect(view.families).toBeNull();
  });
});

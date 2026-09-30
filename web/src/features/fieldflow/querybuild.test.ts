import { describe, expect, it } from "vitest";

import { buildQuery, checkOverride, cleanTerm, draftQueries, hasTerms, QueryError } from "./querybuild";

const kw = (all: string[] = [], any: string[] = [], none: string[] = []) => ({ all, any, none });

describe("query builder (same output as research_agent.querybuild)", () => {
  it("builds Europe PMC with TITLE_ABS, quoted phrases and NOT", () => {
    expect(buildQuery("europepmc", kw(["coronary CT"], ["deep learning", "CNN"], ["review"]))).toBe(
      'TITLE_ABS:"coronary CT" AND (TITLE_ABS:"deep learning" OR TITLE_ABS:CNN) NOT TITLE_ABS:review',
    );
  });

  it("builds OpenAlex without prefixes and one any term without parentheses", () => {
    expect(buildQuery("openalex", kw(["plaque"], ["radiomics"]))).toBe("plaque AND radiomics");
  });

  it("builds arXiv with abs:, the imaging categories and ANDNOT", () => {
    expect(buildQuery("arxiv", kw(["plaque"], [], ["phantom", "survey"]))).toBe(
      "abs:plaque AND (cat:cs.CV OR cat:eess.IV OR cat:physics.med-ph) ANDNOT (abs:phantom OR abs:survey)",
    );
  });

  it("quotes operator words and turns syntax characters into spaces", () => {
    expect(buildQuery("openalex", kw(["AND"]))).toBe('"AND"');
    expect(cleanTerm('CT:"FFR" (deep)')).toBe("CT FFR deep");
  });

  it("drops case-insensitive duplicates", () => {
    expect(buildQuery("openalex", kw(["CT", "ct"], ["MRI", "mri"]))).toBe("CT AND MRI");
  });

  it("keeps a trailing wildcard on one word, for Europe PMC only", () => {
    expect(buildQuery("europepmc", kw(["segment*"]))).toBe("TITLE_ABS:segment*");
    expect(buildQuery("openalex", kw(["segment*"]))).toBe("segment");
    expect(cleanTerm("deep learn*", true)).toBe("deep learn");
  });

  it("refuses a query without All of or Any of terms", () => {
    expect(() => buildQuery("openalex", kw([], [], ["review"]))).toThrow(QueryError);
    expect(hasTerms(kw([], [], ["x"]))).toBe(false);
  });

  it("checks overrides: single line, 2000 characters, no comma for OpenAlex", () => {
    expect(checkOverride("europepmc", "  x AND y ")).toBe("x AND y");
    expect(() => checkOverride("openalex", "a, b")).toThrow("cannot contain a comma");
    expect(() => checkOverride("arxiv", "a\nb")).toThrow("single line");
    expect(() => checkOverride("arxiv", "a".repeat(2001))).toThrow("too long");
  });

  it("gives each chosen source its override, else its built query, else nothing (planned)", () => {
    const rows = draftQueries(kw(["plaque"]), ["openalex", "europepmc"], { openalex: "custom query" });
    expect(rows).toEqual([
      { source: "europepmc", query: "TITLE_ABS:plaque", overridden: false, error: null },
      { source: "openalex", query: "custom query", overridden: true, error: null },
    ]);
    expect(draftQueries(kw(), ["arxiv"], {})).toEqual([{ source: "arxiv", query: null, overridden: false, error: null }]);
    expect(draftQueries(kw(["x"]), ["openalex"], { openalex: "a,b" })[0]!.error).toMatch(/comma/);
  });
});

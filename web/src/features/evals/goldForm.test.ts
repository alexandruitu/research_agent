import { describe, expect, it } from "vitest";

import { goldProblems, parseIncluded } from "./goldForm";

describe("gold set form", () => {
  it("reads one study per line: a DOI, or DOI | title | year, or a title alone", () => {
    expect(parseIncluded("10.1/x | A title | 2020\n\n  10.2/y  \nOnly a title here")).toEqual([
      { doi: "10.1/x", title: "A title", year: "2020" },
      { doi: "10.2/y", title: "", year: "" },
      { doi: "", title: "Only a title here", year: "" },
    ]);
  });

  it("strips doi.org prefixes", () => {
    expect(parseIncluded("https://doi.org/10.3/z")[0]!.doi).toBe("10.3/z");
  });

  it("names every missing field in words", () => {
    expect(goldProblems({ name: "", citation: "", topic: "t", query: "q", included: "" })).toEqual([
      "Give the gold set a name.", "Cite the systematic review.", "List at least one included study.",
    ]);
    expect(goldProblems({ name: "n", citation: "c", topic: "t", query: "q", included: "10.1/x" })).toEqual([]);
  });
});

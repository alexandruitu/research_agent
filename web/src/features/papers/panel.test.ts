import { describe, expect, it } from "vitest";

import { panelOut } from "../../test/fixtures";
import { answerParts, disagreementSentence, listWords, textSentence } from "./panel";

describe("peer review wording", () => {
  it("names every answer with an icon and a word", () => {
    expect(answerParts("not_reported")).toEqual({ icon: "–", word: "not reported" });
    expect(answerParts("yes")).toEqual({ icon: "✓", word: "yes" });
  });

  it("says which text was reviewed", () => {
    expect(textSentence(panelOut())).toBe("Reviewed on the full text from PMC (Methods, Results; 41 000 characters, cut to the length limit).");
    expect(textSentence({ ...panelOut(), text_source: "abstract", text_reason: "pmc_oa: no PMCID" })).toBe("Reviewed on the abstract only (pmc_oa: no PMCID).");
    expect(textSentence({ ...panelOut(), text_licence: "cc-by" })).toMatch(/characters, cut to the length limit\)\. Licence: Creative Commons BY\.$/);
    expect(textSentence({ ...panelOut(), text_source: "sciencedirect", text_sections: [], text_chars: null, text_licence: "publisher_licensed" })).toBe(
      "Reviewed on the full text from ScienceDirect. Licence: publisher licence (your institution's entitlement; not redistributed).",
    );
    expect(textSentence({ ...panelOut(), text_source: "abstract", text_reason: null, text_licence: "abstract" })).toBe("Reviewed on the abstract only.");
  });

  it("puts disagreements in words with reviewer names and the item text", () => {
    const panel = panelOut();
    expect(disagreementSentence(panel, panel.editor.disagreements[0]!)).toBe(
      "Methodologist and Statistician disagree on m1 (“Data were split at patient level, not image level.”): the methods section is ambiguous about the split.",
    );
    expect(listWords(["A", "B", "C"])).toBe("A, B and C");
  });
});

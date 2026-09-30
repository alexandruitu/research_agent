import { describe, expect, it } from "vitest";

import { legacyVersion, versionOut } from "../../test/fixtures";
import { addTerms, effectiveTopic, emptyForm, formFromVersion, moveItem, noOverrides, toBody, toDraft, validate, type FieldForm } from "./fieldForm";

const good = (): FieldForm => ({ ...emptyForm(["europepmc"]), name: "Plaque", topic: "AI plaque on CCTA", include: ["Uses deep learning."] });

describe("field form", () => {
  it("accepts a complete form", () => {
    expect(validate(good())).toEqual([]);
  });

  it("lists every problem in form order", () => {
    expect(validate({ ...emptyForm([]), include: ["ok", " "], exclude: [""] })).toEqual([
      "Give the field a name.", "Describe the field or add keywords.", "Inclusion criterion 2 is empty.", "Exclusion criterion 1 is empty.", "Choose at least one source.",
    ]);
  });

  it("needs at least one criterion", () => {
    expect(validate({ ...good(), include: [] })).toEqual(["Add at least one inclusion or exclusion criterion."]);
  });

  it("checks the years", () => {
    expect(validate({ ...good(), yearFrom: "18" })).toEqual(["Years must be four-digit years between 1900 and 2100."]);
    expect(validate({ ...good(), yearFrom: "2022", yearTo: "2019" })).toEqual(["The first year is after the last year."]);
    expect(validate({ ...good(), yearFrom: "2018" })).toEqual([]);
  });

  it("builds the request body with trimmed texts and numeric years", () => {
    expect(toBody({ ...good(), exclude: [" A review. "], yearFrom: "2018", note: " first " })).toEqual({
      name: "Plaque", topic: "AI plaque on CCTA", include: [{ text: "Uses deep learning." }], exclude: [{ text: "A review." }],
      sources: ["europepmc"], years: { from: 2018, to: null }, note: "first",
    });
  });

  it("loads a saved version; a legacy version has nothing to edit", () => {
    expect(formFromVersion(versionOut())).toEqual({
      name: "ML CT-FFR", topic: "deep learning CT-FFR", description: "", keywords: { all: [], any: [], none: [] },
      overrides: noOverrides(),
      include: ["The study uses machine learning or deep learning.", "FFR is estimated from coronary CT angiography."],
      exclude: ["The paper is a review or an editorial."], sources: ["europepmc"], yearFrom: "2018", yearTo: "", note: "",
    });
    expect(formFromVersion(legacyVersion())).toMatchObject({ include: [], exclude: [], yearFrom: "", yearTo: "" });
  });

  it("derives the topic from the description, else from the keywords", () => {
    const base = { ...emptyForm(["openalex"]), name: "P", include: ["x y z"] };
    expect(effectiveTopic({ ...base, description: "Plaque on CCTA with AI. More text here." })).toBe("Plaque on CCTA with AI.");
    expect(effectiveTopic({ ...base, keywords: { all: ["plaque"], any: ["CNN"], none: [] } })).toBe("plaque CNN");
    expect(validate({ ...base, keywords: { all: ["plaque"], any: [], none: [] } })).toEqual([]);
  });

  it("refuses Exclude alone, long keywords and a comma in the OpenAlex override", () => {
    expect(validate({ ...good(), keywords: { all: [], any: [], none: ["review"] } })).toEqual(["Add a keyword to Must include or At least one of (Exclude alone cannot search)."]);
    expect(validate({ ...good(), keywords: { all: ["x".repeat(81)], any: [], none: [] } })).toEqual(["A keyword in Must include is longer than 80 characters."]);
    expect(validate({ ...good(), overrides: { ...noOverrides(), openalex: "a, b" } })).toEqual(["The OpenAlex query cannot contain a comma."]);
  });

  it("sends description, keywords and overrides only when set", () => {
    expect(toDraft(good())).not.toHaveProperty("keywords");
    const draft = toDraft({ ...good(), description: " About plaque. ", keywords: { all: [" plaque "], any: [], none: [""] }, overrides: { ...noOverrides(), arxiv: " abs:x " } });
    expect(draft).toMatchObject({ description: "About plaque.", keywords: { all: ["plaque"], any: [], none: [] }, query_override: { arxiv: "abs:x" } });
  });

  it("adds terms without duplicates or empties", () => {
    expect(addTerms(["CT"], ["ct", " deep  learning ", "", "MRI"])).toEqual(["CT", "deep learning", "MRI"]);
  });

  it("moves an item and ignores moves past either end", () => {
    expect(moveItem(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
    expect(moveItem(["a", "b"], 1, 1)).toEqual(["a", "b"]);
  });
});

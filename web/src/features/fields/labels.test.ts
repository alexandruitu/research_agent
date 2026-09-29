import { describe, expect, it } from "vitest";

import { criterionLabel, isFieldCriterion, sourceLabel } from "./labels";

describe("labels", () => {
  it("names field criteria by kind and position, and anything else by its key", () => {
    expect(criterionLabel("i1")).toBe("incl 1");
    expect(criterionLabel("e12")).toBe("excl 12");
    expect(criterionLabel("topic_match")).toBe("topic match");
    expect(isFieldCriterion("i3")).toBe(true);
    expect(isFieldCriterion("topic_match")).toBe(false);
  });

  it("names the sources, and passes unknown names through", () => {
    expect(sourceLabel("europepmc")).toBe("Europe PMC");
    expect(sourceLabel("openalex")).toBe("OpenAlex");
    expect(sourceLabel("arxiv")).toBe("arXiv");
    expect(sourceLabel("somewhere")).toBe("somewhere");
  });
});

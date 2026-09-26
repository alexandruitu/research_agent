import { describe, expect, it } from "vitest";

import { PAGE_SIZE, parseView, patchView } from "./papersState";

const q = (text: string) => new URLSearchParams(text);

describe("parseView", () => {
  it("has sensible defaults", () => {
    const view = parseView(q(""));
    expect(view).toEqual({
      runId: null, paperId: null, stageId: null,
      params: { page: 1, page_size: PAGE_SIZE, sort: "title", direction: "asc" },
    });
  });

  it("reads every parameter", () => {
    const view = parseView(q("run=r1&page=3&sort=criterion:topic_match&dir=desc&decision=exclude&tier=jev&escalated=true&in_sr=false&pmin=0.4&pmax=0.6&paper=p1"));
    expect(view.runId).toBe("r1");
    expect(view.paperId).toBe("p1");
    expect(view.params).toEqual({
      page: 3, page_size: PAGE_SIZE, sort: "criterion:topic_match", direction: "desc", decision: "exclude", tier: "jev",
      escalated: true, in_sr: false, criterion: "topic_match", p_min: 0.4, p_max: 0.6,
    });
  });

  it("ignores values the API would reject", () => {
    const view = parseView(q("page=0&sort=drop table&dir=sideways&decision=maybe&tier=x&pmin=abc&pmax=2"));
    expect(view.params).toEqual({ page: 1, page_size: PAGE_SIZE, sort: "title", direction: "asc" });
    expect(parseView(q("page=100001")).params.page).toBe(1); // the API caps page at 100000
    expect(parseView(q("page=100000")).params.page).toBe(100000);
    // p_min above p_max is a 422: drop the range rather than send it
    expect(parseView(q("pmin=0.7&pmax=0.2")).params).toEqual({ page: 1, page_size: PAGE_SIZE, sort: "title", direction: "asc" });
  });
});

describe("patchView", () => {
  it("changing a filter, the sort or the run goes back to page 1", () => {
    expect(patchView(q("page=4&run=r1"), { decision: "exclude" }).get("page")).toBeNull();
    expect(patchView(q("page=4"), { sort: "year" }).get("page")).toBeNull();
    expect(patchView(q("page=4"), { run: "r2" }).get("page")).toBeNull();
    expect(patchView(q("page=4"), { page: 5 }, false).get("page")).toBe("5");
  });

  it("null removes a parameter and booleans are stored as text", () => {
    const next = patchView(q("decision=exclude&escalated=true"), { decision: null, in_sr: true });
    expect(next.toString()).toBe("escalated=true&in_sr=true");
  });

  it("a paper and a stage panel are mutually exclusive, and changing the run closes both", () => {
    expect(patchView(q("stage=screen"), { paper: "p1" }, false).toString()).toBe("paper=p1");
    expect(patchView(q("paper=p1"), { stage: "screen" }, false).toString()).toBe("stage=screen");
    expect(patchView(q("paper=p1&run=r1"), { run: "r2" }).toString()).toBe("run=r2");
  });

  it("does not mutate the input", () => {
    const original = q("page=2");
    patchView(original, { page: 3 }, false);
    expect(original.toString()).toBe("page=2");
  });
});

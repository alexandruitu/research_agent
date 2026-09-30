import { describe, expect, it } from "vitest";

import { sourceRows } from "../../test/fixtures";
import { authWords, enableBlocked, groupSources, keyStatusWords, keyTone, rateWords, searchable } from "./sources";

const byName = (name: string) => sourceRows().find((s) => s.name === name)!;

describe("sources page helpers", () => {
  it("groups sources in reading order and skips empty groups", () => {
    const groups = groupSources(sourceRows());
    expect(groups.map((g) => g.key)).toEqual(["biomedical", "preprints", "multidisciplinary", "publishers", "identity"]);
    expect(groups[0]!.sources.map((s) => s.name)).toEqual(["europepmc", "pubmed"]);
    expect(groupSources([byName("ieee")]).map((g) => g.title)).toEqual(["Publishers (licensed)"]);
  });

  it("says what each source needs in words, naming variables only", () => {
    expect(authWords(byName("europepmc"))).toBe("No key needed");
    expect(authWords(byName("pubmed"))).toBe("Optional key: set NCBI_API_KEY for higher limits");
    expect(authWords(byName("ieee"))).toBe("Key required: set IEEE_API_KEY");
    expect(authWords({ ...byName("ieee"), env: ["ELSEVIER_API_KEY", "ELSEVIER_INSTTOKEN"] })).toBe("Key required: set ELSEVIER_API_KEY and ELSEVIER_INSTTOKEN");
  });

  it("reports the worker's key status: accepted, rejected, not checked, missing, unknown", () => {
    expect(keyStatusWords(byName("europepmc"))).toBeNull();
    expect(keyStatusWords(byName("core"))).toBe("Key set · accepted");
    expect(keyStatusWords({ ...byName("core"), key_accepted: false })).toBe("Key set · rejected");
    expect(keyStatusWords({ ...byName("core"), key_accepted: null, key_detail: "check failed" })).toBe("Key set · not checked (the check failed)");
    expect(keyStatusWords(byName("ieee"))).toBe("Key not set in the worker");
    expect(keyStatusWords(byName("pubmed"))).toBe("Key not set: lower rate limit");
    expect(keyStatusWords({ ...byName("ieee"), key_checked_at: null })).toMatch(/no worker has reported/);
    expect([keyTone(byName("core")), keyTone(byName("ieee")), keyTone(byName("pubmed"))]).toEqual(["ok", "bad", "warn"]);
  });

  it("locks enabling a source whose required key is missing, never disabling", () => {
    expect(enableBlocked(byName("ieee"))).toBe("Set IEEE_API_KEY in the worker environment first, then restart the worker.");
    expect(enableBlocked({ ...byName("ieee"), enabled: true })).toBeNull();
    expect(enableBlocked(byName("pubmed"))).toBeNull();
    expect(enableBlocked(byName("core"))).toBeNull();
  });

  it("describes the rate limit and whether a source can be searched", () => {
    expect(rateWords(byName("europepmc"))).toBe("10 requests / s");
    expect(rateWords(byName("core"))).toBe("1 request every 6 s");
    expect(rateWords(byName("arxiv"))).toBe("paced by the connector");
    expect(searchable(byName("unpaywall"))).toBe(false);
  });
});

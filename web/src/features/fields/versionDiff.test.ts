import { describe, expect, it } from "vitest";

import { legacyVersion, versionOut } from "../../test/fixtures";
import { diffVersions, hasChanges } from "./versionDiff";

describe("version diff", () => {
  it("says, section by section, what was added and removed", () => {
    const sections = diffVersions(legacyVersion(), versionOut());
    const find = (title: string) => sections.find((s) => s.title === title)?.lines;
    expect(find("Name")).toEqual([{ change: "unchanged", text: "ML CT-FFR" }]);
    expect(find("Inclusion criteria")).toEqual([
      { change: "added", text: "The study uses machine learning or deep learning." },
      { change: "added", text: "FFR is estimated from coronary CT angiography." },
    ]);
    expect(find("Legacy topic match")).toEqual([{ change: "removed", text: "The paper's central subject is the topic." }]);
    expect(find("Sources")).toEqual([{ change: "unchanged", text: "Europe PMC" }]);
    expect(find("Years")).toEqual([{ change: "removed", text: "any year – now" }, { change: "added", text: "2018 – now" }]);
    expect(hasChanges(sections)).toBe(true);
  });

  it("finds nothing between a version and itself, and a reworded criterion is removed plus added", () => {
    expect(hasChanges(diffVersions(versionOut(), versionOut()))).toBe(false);
    const reworded = versionOut({ exclude: [{ key: "e1", text: "The paper is a review." }] });
    expect(diffVersions(versionOut(), reworded).find((s) => s.title === "Exclusion criteria")?.lines).toEqual([
      { change: "removed", text: "The paper is a review or an editorial." },
      { change: "added", text: "The paper is a review." },
    ]);
  });
});

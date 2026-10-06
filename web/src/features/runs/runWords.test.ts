import { describe, expect, it } from "vitest";

import { canManageRun, formatSeconds, formatUsd, runLabel } from "./runWords";

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

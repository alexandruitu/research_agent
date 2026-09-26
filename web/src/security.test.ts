import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

const sources = walk("src").filter(
  (path) =>
    /\.(ts|tsx)$/.test(path) &&
    !path.endsWith(".test.ts") &&
    !path.endsWith(".test.tsx") &&
    !path.includes("/test/") &&
    !path.endsWith("schema.d.ts"),
);

describe("what the Content-Security-Policy relies on", () => {
  it("finds the source files", () => {
    expect(sources.length).toBeGreaterThan(20);
  });

  it("uses no inline style attributes (the CSP has no 'unsafe-inline' for styles)", () => {
    const offenders = sources.filter((path) => /\bstyle=\{/.test(readFileSync(path, "utf8")));
    expect(offenders).toEqual([]);
  });

  it("never injects HTML and never evaluates strings", () => {
    const offenders = sources.filter((path) =>
      /dangerouslySetInnerHTML|\.innerHTML\s*=|(?<![.\w])eval\(|new Function\(/.test(readFileSync(path, "utf8")),
    );
    expect(offenders).toEqual([]);
  });

  it("index.html has one external module script and no inline script or style", () => {
    const html = readFileSync("index.html", "utf8");
    expect(html.match(/<script\b[^>]*>/g)?.every((tag) => /\bsrc=/.test(tag))).toBe(true);
    expect(html).not.toMatch(/<style\b/);
    expect(html).not.toMatch(/\son[a-z]+=/i);
  });
});

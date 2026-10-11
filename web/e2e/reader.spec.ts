import { expect, test } from "@playwright/test";

import { auth } from "./users";

test.describe("member", () => {
  test.use({ storageState: auth("member") });

  test("opens a paper in the Reader, explains a selected sentence and saves the answer as a note", async ({ page }) => {
    test.setTimeout(60_000);
    // the imported demo research run and one of its papers, found through the API
    const runs = await (await page.request.get("/api/v1/runs")).json();
    const run = runs.find((r: { kind: string; status: string }) => r.kind === "research" && r.status === "done");
    const papers = await (await page.request.get(`/api/v1/runs/${run.id}/papers`, { params: { page_size: 50, decision: "include" } })).json();
    const paper = papers.items.find((row: { paper: { abstract?: string } }) => row.paper.abstract) ?? papers.items[0];
    await page.goto(`/read/${run.id}/${paper.paper.id}`);
    const text = page.getByRole("article", { name: "Paper text" });
    await expect(text).toBeVisible();
    await expect(text.getByText(/Abstract only/)).toBeVisible();

    // select the first sentence of the text, as a reader would with the mouse
    const sentence = await text.locator(".reader-paragraph").first().evaluate((p) => {
      const node = [...p.querySelectorAll("span, mark")].map((e) => e.firstChild).find((n) => n && n.nodeType === Node.TEXT_NODE && (n.textContent ?? "").includes("."))!;
      const value = node.textContent ?? "";
      const end = value.indexOf(".") + 1;
      const range = document.createRange();
      range.setStart(node, 0);
      range.setEnd(node, end);
      const selection = window.getSelection()!;
      selection.removeAllRanges();
      selection.addRange(range);
      p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
      return value.slice(0, end).trim();
    });
    await expect(page.getByText(/^Selected:/)).toBeVisible();

    const panel = page.getByRole("complementary", { name: "Reading tools" });
    await panel.getByRole("button", { name: "Explain (from the paper)" }).click();
    await expect(panel.getByText(/SIMULATED explanation from the paper text/)).toBeVisible({ timeout: 30_000 });
    await expect(panel.locator("q.reader-quote").first()).toHaveText(sentence);
    await panel.getByRole("button", { name: "Save as note" }).click();
    await expect(panel.getByText("Note saved.")).toBeVisible();
    await expect(panel.locator(".reader-note-list")).toContainText(sentence);
  });

  test("builds the paper map (demo) and jumps from a node to its quote in the text", async ({ page }) => {
    test.setTimeout(60_000);
    const runs = await (await page.request.get("/api/v1/runs")).json();
    const run = runs.find((r: { kind: string; status: string }) => r.kind === "research" && r.status === "done");
    const papers = await (await page.request.get(`/api/v1/runs/${run.id}/papers`, { params: { page_size: 50, decision: "include" } })).json();
    const paper = papers.items.find((row: { paper: { abstract?: string } }) => row.paper.abstract) ?? papers.items[0];
    await page.goto(`/read/${run.id}/${paper.paper.id}`);
    await page.getByRole("tab", { name: "Map" }).click();
    const map = page.getByRole("tabpanel", { name: "Map" });
    const build = map.getByRole("button", { name: /^(Build the paper map|Rebuild)$/ });
    const outline = map.getByRole("list", { name: "Paper map outline" });
    await expect(build.or(outline).first()).toBeVisible();
    if (await build.isVisible()) await build.click(); // a map kept from an earlier run of this test is reused
    await expect(outline).toBeVisible({ timeout: 30_000 });
    await expect(map.getByRole("img", { name: /^Paper map of/ })).toBeVisible();
    await expect(map.getByText("From the abstract only")).toBeVisible();
    const node = outline.locator("button.map-outline__node").first();
    const quote = ((await node.getAttribute("aria-describedby")) ?? "");
    const said = (await page.locator(`[id="${quote}"]`).textContent()) ?? "";
    await node.click();
    await expect(page.getByRole("tab", { name: "Text" })).toHaveAttribute("aria-selected", "true");
    const mark = page.locator("#map-focus");
    await expect(mark).toBeFocused();
    await expect(mark).toHaveClass(/is-lit/);
    expect(said).toContain((await mark.textContent())!.replace(/^(Red flag|Claim|Map) quote: /, "").slice(0, 30));
    await expect(mark).not.toHaveClass(/is-lit/, { timeout: 5_000 }); // the highlight fades after 2 s
  });

  test("finds related work for a selected sentence (demo sources, no network)", async ({ page }) => {
    test.setTimeout(60_000);
    const runs = await (await page.request.get("/api/v1/runs")).json();
    const run = runs.find((r: { kind: string; status: string }) => r.kind === "research" && r.status === "done");
    const papers = await (await page.request.get(`/api/v1/runs/${run.id}/papers`, { params: { page_size: 50, decision: "include" } })).json();
    const paper = papers.items.find((row: { paper: { abstract?: string } }) => row.paper.abstract) ?? papers.items[0];
    await page.goto(`/read/${run.id}/${paper.paper.id}`);
    const text = page.getByRole("article", { name: "Paper text" });
    await expect(text).toBeVisible();
    await text.locator(".reader-paragraph").first().evaluate((p) => {
      const node = [...p.querySelectorAll("span, mark")].map((e) => e.firstChild).find((n) => n && n.nodeType === Node.TEXT_NODE && (n.textContent ?? "").includes("."))!;
      const range = document.createRange();
      range.setStart(node, 0);
      range.setEnd(node, (node.textContent ?? "").indexOf(".") + 1);
      window.getSelection()!.removeAllRanges();
      window.getSelection()!.addRange(range);
      p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    });
    await expect(page.getByText(/^Selected:/)).toBeVisible();
    const panel = page.getByRole("complementary", { name: "Reading tools" });
    await panel.getByRole("button", { name: "Find related" }).click();
    await expect(panel.getByRole("heading", { name: /^Related papers \(\d+\)$/ })).toBeVisible({ timeout: 30_000 });
    await expect(panel.getByText(/key terms \(code, no AI\)/)).toBeVisible();
    await expect(panel.locator(".reader-related-item").first()).toBeVisible();
    await expect(panel.getByText(/seen in run/).first()).toBeVisible();
    await expect(panel.locator(".reader-related-item", { hasText: paper.paper.title })).toHaveCount(0);
  });

  test("opens from a Results row, uses the full width with text and tools side by side, and goes back to Results", async ({ page }) => {
    await page.setViewportSize({ width: 1400, height: 900 });
    const runs = await (await page.request.get("/api/v1/runs")).json();
    const run = runs.find((r: { kind: string; status: string; paper_count: number }) => r.kind === "research" && r.status === "done" && r.paper_count > 0);
    await page.goto(`/results?run=${run.id}&group=none`);
    const resultsUrl = page.url();
    await page.locator("table.papers tbody tr").first().getByRole("link", { name: "Read" }).click();
    const text = page.getByRole("article", { name: "Paper text" });
    const tools = page.getByRole("complementary", { name: "Reading tools" });
    await expect(text).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Research steps" }).locator("[aria-current=step]")).toContainText("Read");
    const [a, b] = [await text.boundingBox(), await tools.boundingBox()];
    expect(a!.x + a!.width).toBeLessThanOrEqual(b!.x); // side by side
    expect(a!.width / (a!.width + b!.width)).toBeGreaterThan(0.5); // the text gets the larger share
    expect(a!.width + b!.width).toBeGreaterThan(1200); // past the 1440px page column: the whole viewport
    await expect(tools.getByRole("heading", { name: "Understand" })).toBeVisible();
    await expect(tools.getByRole("button", { name: "In-house" })).toBeDisabled();
    await page.getByRole("link", { name: "Back to Results" }).click();
    await expect(page).toHaveURL(resultsUrl);
  });

  test("stacks the text above the tools on a narrow screen", async ({ page }) => {
    await page.setViewportSize({ width: 600, height: 900 });
    const runs = await (await page.request.get("/api/v1/runs")).json();
    const run = runs.find((r: { kind: string; status: string; paper_count: number }) => r.kind === "research" && r.status === "done" && r.paper_count > 0);
    const papers = await (await page.request.get(`/api/v1/runs/${run.id}/papers`, { params: { page_size: 5 } })).json();
    await page.goto(`/read/${run.id}/${papers.items[0].paper.id}`);
    const text = page.getByRole("article", { name: "Paper text" });
    await expect(text).toBeVisible();
    const [a, b] = [await text.boundingBox(), await page.getByRole("complementary", { name: "Reading tools" }).boundingBox()];
    expect(b!.y).toBeGreaterThanOrEqual(a!.y + a!.height);
    // nothing pokes out sideways (named in the failure, so it is clear what to fix)
    const wide = await page.evaluate(() => [...document.querySelectorAll("body *")]
      .filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1 && getComputedStyle(e).position !== "fixed")
      .map((e) => `${e.tagName.toLowerCase()}.${[...e.classList].join(".")}`).slice(0, 8));
    expect(wide).toEqual([]);
  });
});

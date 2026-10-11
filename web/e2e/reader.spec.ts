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
});

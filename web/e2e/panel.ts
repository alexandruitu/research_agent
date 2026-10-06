import { expect, type Page } from "@playwright/test";

/** Starts a small demo run from the Runs page (a panel run: every new run freezes the review settings) and opens its papers. */
export async function startDemoRunAndOpenPapers(page: Page, papers = 3) {
  await page.goto("/runs");
  await page.getByRole("combobox", { name: "Field", exact: true }).selectOption({ index: 1 });
  await page.getByLabel("Papers to screen").fill(String(papers));
  await page.getByLabel(/Demo mode/).check();
  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page.getByRole("status", { name: "Run progress" })).toContainText("done", { timeout: 150_000 });
  await page.locator("table.runs tbody tr").filter({ hasText: "research" }).first().getByRole("link", { name: /^Papers of / }).click();
  await page.getByRole("button", { name: "Detailed", exact: true }).click(); // Simple is the default view
  await page.getByRole("combobox", { name: "Group by" }).selectOption({ label: "None (flat list)" });
  await expect(page.locator("table.papers tbody tr").first()).toBeVisible();
}

/** Opens the first paper the panel reviewed (it has a score cell) and waits for its Peer review step. */
export async function openReviewedPaper(page: Page) {
  const row = page.locator("table.papers tbody tr").filter({ has: page.locator(".panel-score") }).first();
  await row.locator("[data-open-paper]").click();
  const drawer = page.getByRole("complementary", { name: "Paper details" });
  await expect(drawer.getByRole("heading", { name: "Peer review" })).toBeVisible();
  return drawer;
}

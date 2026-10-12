import { expect, test } from "@playwright/test";

import { auth } from "./users";

test.use({ storageState: auth("member") });

test("a researcher topic: find the person, pick them, keep frequent co-authors, run it, see Matched by", async ({ page }) => {
  test.setTimeout(240_000);
  const name = `E2E researcher ${Date.now()}`; // the browser-test database outlives one run
  await page.goto("/topics");
  await page.getByRole("link", { name: "New topic" }).click();
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel(/Demo mode/).check();
  await page.getByRole("button", { name: "Next →" }).click();
  await page.getByRole("button", { name: /^Researcher/ }).click();
  await page.getByRole("textbox", { name: "Researcher name" }).fill("Ada Lovelace");
  await page.getByRole("button", { name: "Find researcher" }).click();
  await page.getByRole("checkbox", { name: /Ada Lovelace .*42 works/ }).check({ timeout: 60_000 });
  await page.getByRole("button", { name: "Use selected (1)" }).click();
  const coauthors = page.getByRole("list", { name: "Co-authors" });
  await expect(coauthors.getByRole("checkbox", { name: /Synthetic Coauthor One/ })).toBeChecked({ timeout: 60_000 });
  await expect(coauthors.getByRole("checkbox", { name: /Synthetic Coauthor Two/ })).toBeChecked(); // 3 shared works
  await expect(coauthors.getByRole("checkbox", { name: /Synthetic Coauthor Three/ })).not.toBeChecked(); // 1 shared work
  await page.getByRole("button", { name: "Next →" }).click();
  await page.getByRole("button", { name: "Create topic" }).click();
  await expect(page.getByRole("heading", { name: `${name} (v1)` })).toBeVisible();

  await page.goto("/topics");
  await page.getByRole("link", { name: `Start run for ${name}` }).click();
  await page.getByLabel("Papers to screen").fill("10");
  await page.getByLabel(/Demo mode/).check();
  await page.getByRole("button", { name: "Start run" }).click();
  await expect(page.getByRole("status", { name: "Run progress" })).toContainText("done", { timeout: 120_000 });
  await page.locator("table.runs tbody tr").filter({ hasText: name }).first().getByRole("link", { name: /^Results of / }).click();
  const papers = page.locator("table.papers");
  await expect(papers).toContainText("Matched by: the person (Ada Lovelace)", { timeout: 30_000 });
  await expect(papers).toContainText("co-author Synthetic Coauthor One");
  await expect(papers).toContainText("name match: Ada Lovelace");
  await page.getByRole("combobox", { name: "Matched by" }).selectOption("coauthor");
  await expect(page.locator("table.papers tbody tr")).toHaveCount(2);
  await expect(page).toHaveURL(/match=coauthor/);
});

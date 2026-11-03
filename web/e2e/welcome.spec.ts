import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { auth } from "./users";

test.use({ storageState: auth("member") });

test("the first-use guide: 3 steps with done states, hidden on request, back from How it works, accessible", async ({ page }) => {
  // auth.setup dismissed it; forget that choice to see what a new user sees
  await page.goto("/topics");
  await page.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("welcome-dismissed:")).forEach((k) => localStorage.removeItem(k)));
  await page.reload();
  const guide = page.getByRole("region", { name: /From a question to papers worth reading/ });
  await expect(guide).toBeVisible();
  // the browser-test database already has topics, so the first step is marked done in words
  await expect(guide.getByRole("heading", { name: /Create a topic.*done/ })).toBeVisible();
  await expect(guide.getByRole("link", { name: /Start a search/ })).toHaveAttribute("href", "/screening");
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  expect(results.violations.map((v) => v.id), "accessibility violations").toEqual([]);

  await guide.getByRole("button", { name: "Hide this guide" }).click();
  await expect(guide).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Topics" })).toBeVisible();
  await expect(guide).toHaveCount(0);

  await page.getByRole("button", { name: "How it works" }).click();
  await expect(guide).toBeVisible();
  await guide.getByRole("button", { name: "Hide this guide" }).click();
});

test("a search row says what it did in one plain line", async ({ page }) => {
  await page.goto("/screening");
  await expect(page.getByRole("heading", { level: 1, name: "Search" })).toBeVisible();
  await expect(page.locator(".runs__summary").first()).toHaveText(/^(Searched|Waiting|Searching)/);
});

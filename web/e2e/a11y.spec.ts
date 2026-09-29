import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { auth } from "./users";

async function audit(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const found = results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`);
  expect(found, "accessibility violations").toEqual([]);
}

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });
  test("sign-in page", async ({ page }) => {
    await page.goto("/login");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await audit(page);
  });
});

test.describe("viewer", () => {
  test.use({ storageState: auth("viewer") });

  test("papers table with the pipeline strip", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await expect(page.locator("table.papers tbody tr").first()).toBeVisible();
    await audit(page);
  });

  test("paper drawer open", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await page.locator("[data-open-paper]").first().click();
    await expect(page.getByRole("complementary", { name: "Paper details" })).toBeVisible();
    await audit(page);
  });

  test("stage panel open", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await page.getByRole("button", { name: /^Screen/ }).click();
    await expect(page.getByRole("complementary", { name: "About Screen" })).toBeVisible();
    await audit(page);
  });

  test("evals", async ({ page }) => {
    await page.goto("/evals");
    await expect(page.getByRole("table", { name: "Threshold grid" })).toBeVisible();
    await audit(page);
  });

  test("system map with a panel", async ({ page }) => {
    await page.goto("/system?stage=reviewers");
    await expect(page.getByRole("complementary", { name: "About Reviewers A and B" })).toBeVisible();
    await audit(page);
  });
});

test.describe("member", () => {
  test.use({ storageState: auth("member") });
  test("runs with the start form", async ({ page }) => {
    await page.goto("/runs");
    await expect(page.getByRole("button", { name: "Start run" })).toBeVisible();
    await audit(page);
  });
});

test.describe("fields and settings", () => {
  test.describe("member", () => {
    test.use({ storageState: auth("member") });
    test("fields list", async ({ page }) => {
      await page.goto("/fields");
      await expect(page.getByRole("heading", { name: "Fields" })).toBeVisible();
      await audit(page);
    });
    test("field editor with test results", async ({ page }) => {
      test.setTimeout(90_000);
      await page.goto("/fields");
      await page.locator("table.runs tbody tr a").first().click();
      await expect(page.getByRole("form", { name: "Field editor" })).toBeVisible();
      await page.getByRole("button", { name: "Add inclusion criterion" }).click();
      await page.getByLabel("incl 1", { exact: true }).fill("The study uses deep learning.");
      await page.getByLabel(/Demo mode/).check();
      await page.getByRole("button", { name: "Test criteria" }).click();
      await expect(page.getByRole("region", { name: "Criteria test" }).getByRole("table")).toBeVisible({ timeout: 60_000 });
      await audit(page);
    });
  });
  test.describe("viewer", () => {
    test.use({ storageState: auth("viewer") });
    for (const tab of ["sources", "models"]) {
      test(`settings ${tab} (read-only)`, async ({ page }) => {
        await page.goto(`/settings/${tab}`);
        await expect(page.getByRole("navigation", { name: "Settings sections" })).toBeVisible();
        await expect(page.getByText(/Read-only/)).toBeVisible();
        await audit(page);
      });
    }
  });
  test.describe("admin", () => {
    test.use({ storageState: auth("admin") });
    for (const tab of ["sources", "models", "users"]) {
      test(`settings ${tab}`, async ({ page }) => {
        await page.goto(`/settings/${tab}`);
        await expect(page.getByRole("navigation", { name: "Settings sections" })).toBeVisible();
        await expect(page.getByRole("heading", { level: 2 })).toBeVisible();
        await audit(page);
      });
    }
  });
});

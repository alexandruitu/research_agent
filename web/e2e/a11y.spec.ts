import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { openReviewedPaper, startDemoRunAndOpenPapers } from "./panel";
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
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /^Papers of / }).click();
    await expect(page.locator("table.papers tbody tr").first()).toBeVisible();
    await audit(page);
  });

  test("paper drawer open", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /^Papers of / }).click();
    await page.locator("[data-open-paper]").first().click();
    await expect(page.getByRole("complementary", { name: "Paper details" })).toBeVisible();
    await audit(page);
  });

  test("stage panel open", async ({ page }) => {
    await page.goto("/system"); // the pipeline strip moved from Papers to the System map
    await page.getByRole("button", { name: /^Screen/ }).click();
    await expect(page.getByRole("complementary", { name: "About Screen" })).toBeVisible();
    await audit(page);
  });

  test("evals", async ({ page }) => {
    await page.goto("/evals");
    await page.getByRole("article", { name: /^Screening/ }).first().getByRole("link", { name: /Open report/ }).click();
    await expect(page.getByRole("table", { name: "Threshold grid" })).toBeVisible();
    await page.goto("/evals");
    await audit(page);
    await page.goBack();
    await audit(page);
  });

  test("system map with a panel", async ({ page }) => {
    await page.goto("/system?stage=reviewers");
    await expect(page.getByRole("complementary", { name: "About Review panel" })).toBeVisible();
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
    test("field editor: every step, with suggestions, preview and test results", async ({ page }) => {
      test.setTimeout(150_000);
      await page.goto("/fields/new");
      await page.getByLabel("Description").fill("Deep learning for coronary plaque on CT angiography.");
      await page.getByLabel(/Demo mode/).check();
      await page.getByRole("button", { name: "Suggest keywords & criteria" }).click();
      await expect(page.getByRole("region", { name: /Suggestions/ })).toBeVisible({ timeout: 60_000 });
      await audit(page);
      await page.getByRole("button", { name: "Accept all" }).click();
      await page.getByRole("button", { name: "Next →" }).click();
      await page.getByText(/Advanced: override query/).click();
      await audit(page);
      await page.getByRole("button", { name: "Next →" }).click();
      await page.getByRole("button", { name: "Preview search" }).click();
      await expect(page.getByRole("region", { name: "Search preview" }).locator(".preview-source").first()).toBeVisible({ timeout: 60_000 });
      await audit(page);

      await page.goto("/fields");
      await page.locator("table.runs tbody tr a").first().click();
      await expect(page.getByRole("form", { name: "Field editor" })).toBeVisible();
      await page.getByRole("button", { name: "Add inclusion criterion" }).click();
      await page.getByLabel("incl 1", { exact: true }).fill("The study uses deep learning.");
      await page.getByLabel(/Demo mode/).check();
      await page.getByRole("navigation", { name: "Steps" }).getByRole("button", { name: /Preview & save/ }).click();
      await page.getByRole("button", { name: "Test criteria" }).click();
      await expect(page.getByRole("region", { name: "Criteria test" }).getByRole("table")).toBeVisible({ timeout: 60_000 });
      await audit(page);
    });
  });
  test.describe("viewer", () => {
    test.use({ storageState: auth("viewer") });
    test("reviewers archive open (read-only)", async ({ page }) => {
      await page.goto("/settings/reviewers");
      await page.getByRole("button", { name: "Show archived reviewers" }).click();
      await audit(page);
    });
    for (const tab of ["sources", "models", "reviewers", "screening", "fulltext"]) {
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
    for (const tab of ["sources", "models", "users", "reviewers", "screening", "fulltext", "reviewers/methodologist", "reviewers/new"]) {
      test(`settings ${tab}`, async ({ page }) => {
        await page.goto(`/settings/${tab}`);
        await expect(page.getByRole("navigation", { name: "Settings sections" })).toBeVisible();
        await expect(page.getByRole("heading", { level: 2 }).first()).toBeVisible();
        await audit(page);
      });
    }
  });
});

test.describe("library and saving", () => {
  test.use({ storageState: auth("member") });
  test("papers with a selection, the save dialog, the library with its reading pane and collections", async ({ page }) => {
    test.setTimeout(200_000);
    await startDemoRunAndOpenPapers(page);
    await page.locator("table.papers tbody tr").nth(0).getByRole("checkbox").check();
    await expect(page.getByRole("region", { name: "Selection" })).toBeVisible();
    await audit(page);
    await page.getByRole("button", { name: "Save to library…" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await audit(page);
    await page.getByRole("dialog").getByLabel("New collection (optional)").fill(`A11y ${Date.now()}`);
    await page.getByRole("dialog").getByRole("button", { name: "Save to library" }).click();
    await expect(page.getByText(/Saved 1 paper|already in the library/)).toBeVisible();
    await page.locator("[data-open-paper]").first().click();
    await expect(page.getByRole("complementary", { name: "Paper details" })).toBeVisible();
    await audit(page);

    await page.goto("/library");
    await expect(page.getByRole("list", { name: "Saved papers" })).toBeVisible();
    await audit(page);
    await page.getByRole("list", { name: "Saved papers" }).getByRole("button").first().click();
    const pane = page.getByRole("complementary", { name: "Reading pane" });
    await expect(pane.getByRole("radio").first()).toBeVisible();
    await audit(page);
    for (const tab of ["Evidence", /History/]) {
      await pane.getByRole("button", { name: tab }).click();
      await audit(page);
    }
    await page.getByRole("button", { name: "Manage collections" }).click();
    await expect(page.getByRole("region", { name: "Collections" })).toBeVisible();
    await audit(page);
    await page.keyboard.press("?");
    await expect(page.getByRole("dialog", { name: "Library shortcuts" })).toBeVisible();
    await audit(page);
  });
});

test.describe("review panel", () => {
  test.use({ storageState: auth("admin") });
  test("paper drawer with the peer review open", async ({ page }) => {
    test.setTimeout(200_000);
    await startDemoRunAndOpenPapers(page);
    await audit(page);
    const drawer = await openReviewedPaper(page);
    for (const summary of await drawer.locator("details.reviewer-report summary").all()) await summary.click();
    await audit(page);
  });
});

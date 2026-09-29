import { expect, test } from "@playwright/test";

import { openReviewedPaper, startDemoRunAndOpenPapers } from "./panel";
import { auth, EMAIL, PASSWORD } from "./users";

test.describe("signed out", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a wrong password shows an error and stays on the sign-in page", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await page.getByLabel("Email").fill(EMAIL.viewer);
    await page.getByLabel("Password").fill("not the password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });
});

test.describe("viewer", () => {
  test.use({ storageState: auth("viewer") });

  test("cannot see Users or the start form", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("link", { name: "Papers" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Users" })).toHaveCount(0);
    await page.goto("/users");
    await expect(page.getByRole("heading", { name: "Not allowed" })).toBeVisible();
    await page.goto("/runs");
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("button", { name: "Start run" })).toHaveCount(0);
  });

  test("the paper the screen dropped: filter, open, read the story, all from the keyboard", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await page.getByRole("button", { name: "Dropped" }).click();
    await page.getByRole("button", { name: "In the SR", exact: true }).click();
    const row = page.getByRole("row", { name: /MED:3/ });
    await expect(row).toBeVisible();
    const opener = row.getByRole("button").first();
    await opener.focus();
    await page.keyboard.press("Enter");
    const drawer = page.getByRole("complementary", { name: "Paper details" });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("heading").first()).toBeFocused();
    await expect(drawer.getByText("0.03", { exact: true })).toBeVisible();
    await expect(drawer.getByText(/Auto-drop needs/)).toBeVisible();
    await expect(drawer.getByText(/Included by the systematic review/)).toBeVisible();
    await expect(page).toHaveURL(/paper=/);
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(opener).toBeFocused();
  });

  test("the URL is the view: reloading keeps the filters and the open paper", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /See papers/ }).click();
    await page.getByRole("button", { name: "Only escalated" }).click();
    await page.reload();
    await expect(page.getByRole("button", { name: "Only escalated" })).toHaveAttribute("aria-pressed", "true");
  });

  test("System map: a stage is measured only with a measurement", async ({ page }) => {
    await page.goto("/system");
    await expect(page.getByRole("button", { name: /^Search/ })).toHaveAttribute("data-status", "measured");
    await expect(page.getByRole("button", { name: /^Rank/ })).toHaveAttribute("data-status", "unmeasured");
    await page.getByRole("button", { name: /^Rank/ }).click();
    await expect(page.getByRole("complementary", { name: "About Rank" })).toBeVisible();
    await expect(page).toHaveURL(/stage=rank/);
  });

  test("Evals: the threshold grid outlines the shipped default", async ({ page }) => {
    await page.goto("/evals");
    await expect(page.getByRole("region", { name: "Summary" })).toBeVisible();
    await expect(page.getByRole("table", { name: "Threshold grid" })).toBeVisible();
    await expect(page.locator("table[aria-label='Threshold grid'] td.is-default")).toHaveCount(1);
    await expect(page.getByRole("table", { name: "Recall by strategy" })).toContainText("cascade");
  });
});

test.describe("member", () => {
  test.use({ storageState: auth("member") });

  test("starts a demo run, follows it to done and reads its papers", async ({ page }) => {
    test.setTimeout(150_000);
    await page.goto("/runs");
    await page.getByLabel("Field").selectOption({ index: 1 });
    await page.getByLabel("Papers to screen").fill("3");
    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByRole("status", { name: "Run progress" })).toContainText("done", { timeout: 120_000 });
    const row = page.locator("table.runs tbody tr").filter({ hasText: "research" }).filter({ has: page.locator("td", { hasText: /^3$/ }) });
    await row.first().getByRole("link", { name: /See papers/ }).click(); // newest first; other tests start 3-paper runs too
    await expect(page.locator("table.papers tbody tr")).toHaveCount(3);
  });
  test("creates a field, tests its criteria in demo mode, starts a demo run and sees what decided", async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto("/fields");
    await page.getByRole("link", { name: "New field" }).click();
    await page.getByLabel("Name", { exact: true }).fill("E2E plaque");
    await page.getByLabel(/^Topic/).fill("AI plaque characterisation on coronary CT angiography");
    const include = ["The study uses machine learning or deep learning.", "Plaque is assessed on coronary CT angiography."];
    for (const [index, text] of include.entries()) {
      await page.getByRole("button", { name: "Add inclusion criterion" }).click();
      await page.getByLabel(`incl ${index + 1}`, { exact: true }).fill(text);
    }
    await page.getByRole("button", { name: "Add exclusion criterion" }).click();
    await page.getByLabel("excl 1", { exact: true }).fill("The paper is a review or an editorial.");
    await page.getByLabel("Change note").fill("first version");
    await page.getByRole("button", { name: "Create field" }).click();
    await expect(page.getByRole("heading", { name: "E2E plaque (v1)" })).toBeVisible();

    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Test criteria" }).click();
    const results = page.getByRole("region", { name: "Criteria test" });
    await expect(results.getByRole("table")).toBeVisible({ timeout: 60_000 });
    await expect(results).toContainText(/\d+ papers · \d+ kept · \d+ dropped/);

    await page.goto("/fields");
    await page.getByRole("link", { name: "Start run for E2E plaque" }).click();
    await page.getByLabel("Papers to screen").fill("3");
    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByRole("status", { name: "Run progress" })).toContainText("done", { timeout: 120_000 });
    await page.locator("table.runs tbody tr").filter({ hasText: "E2E plaque" }).first().getByRole("link", { name: /See papers/ }).click();
    await expect(page.getByRole("combobox", { name: "Run" })).toContainText("E2E plaque · v1");
    await expect(page.locator("table.papers tbody tr").first()).toContainText(/all met|dropped by (incl|excl) \d|no single criterion decided/);
    await expect(page.getByRole("combobox", { name: "Dropped by criterion" })).toContainText("incl 1: The study uses machine learning or deep learning.");
  });
});

test.describe("admin", () => {
  test.use({ storageState: auth("admin") });

  test("invites a user who can then sign in", async ({ page }) => {
    await page.goto("/settings/users");
    // the label wraps the select, so its accessible name also carries the selected option: scope to the form
    const invite = page.getByRole("form", { name: "Invite a user" });
    await invite.getByLabel("Email").fill("nina@example.org");
    await invite.getByLabel("Name").fill("Nina New");
    await invite.getByLabel(/^Role/).selectOption("viewer");
    await invite.getByLabel("Initial password").fill(PASSWORD);
    await invite.getByRole("button", { name: "Invite" }).click();
    await expect(page.getByRole("cell", { name: "nina@example.org", exact: true })).toBeVisible();

    await page.context().clearCookies();
    await page.goto("/");
    await page.getByLabel("Email").fill("nina@example.org");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Users" })).toHaveCount(0);
  });
});

test.describe("review panel", () => {
  test.use({ storageState: auth("admin") });

  test("an admin edits a reviewer, a demo run uses it, the drawer shows the panel and takes a PDF", async ({ page }) => {
    test.setTimeout(240_000);
    await page.goto("/settings/reviewers");
    await page.getByRole("link", { name: "Methodologist" }).click();
    await expect(page.getByRole("form", { name: "Reviewer editor" })).toBeVisible();
    await page.getByRole("button", { name: "Add item" }).click();
    const count = await page.locator(".item-card").count();
    await page.getByLabel(`Question for item ${count} text`).fill("The reference standard is described for every patient.");
    await page.getByRole("group", { name: `Weight of item ${count}` }).getByText("3 · high").click();
    await page.getByLabel(`Red flag rule for item ${count}`).selectOption("no");
    await expect(page.getByRole("complementary", { name: "What the model reads" })).toContainText("The reference standard is described for every patient.");
    await page.getByLabel("Change note").fill("e2e: reference standard");
    await page.getByRole("button", { name: /^Save as v/ }).click();
    await expect(page.getByRole("status").filter({ hasText: /Saved as v\d+/ })).toBeVisible();

    await startDemoRunAndOpenPapers(page);
    await expect(page.getByRole("columnheader", { name: /Peer review score/ })).toBeVisible();
    const drawer = await openReviewedPaper(page);
    await expect(drawer).toContainText("Editor's decision");
    await drawer.locator("details.reviewer-report summary").filter({ hasText: "Methodologist" }).click();
    await expect(drawer.getByRole("table", { name: "Methodologist's checklist" })).toContainText("The reference standard is described for every patient.");

    await drawer.locator("input[type=file]").setInputFiles({ name: "tiny.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n") });
    await expect(drawer.getByText(/Uploaded tiny.pdf/)).toBeVisible();
    await expect(drawer.locator(".file-name", { hasText: "tiny.pdf" })).toBeVisible();
  });
});

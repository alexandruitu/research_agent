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
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /^Papers of / }).click();
    await page.getByRole("button", { name: "Detailed", exact: true }).click(); // Simple is the default view
    await page.getByRole("combobox", { name: "Group by" }).selectOption({ label: "None (flat list)" }); // groups may start collapsed
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
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /^Papers of / }).click();
    await page.getByRole("button", { name: "Only escalated", exact: true }).click();
    await page.reload();
    await expect(page.getByRole("button", { name: "Only escalated", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("group", { name: "Active filters" })).toContainText("Only escalated");
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
    await page.getByRole("article", { name: /^Screening/ }).first().getByRole("link", { name: /Open report/ }).click();
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
    await page.getByRole("combobox", { name: "Field", exact: true }).selectOption({ index: 1 });
    await page.getByLabel("Papers to screen").fill("3");
    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByRole("status", { name: "Run progress" })).toContainText("done", { timeout: 120_000 });
    const row = page.locator("table.runs tbody tr").filter({ hasText: "research" }).filter({ has: page.locator("td", { hasText: /^3$/ }) });
    await row.first().getByRole("link", { name: /^Papers of / }).click(); // newest first; other tests start 3-paper runs too
    await expect(page.locator("table.papers tbody tr")).toHaveCount(3);
  });
  test("describe a field, accept suggestions, preview, save, run it, keep two papers in the library, find and export them", async ({ page }) => {
    test.setTimeout(240_000);
    await page.goto("/fields");
    await page.getByRole("link", { name: "New field" }).click();
    await page.getByLabel("Name", { exact: true }).fill("E2E plaque");
    await page.getByLabel("Description").fill("Deep learning for coronary plaque characterisation on CT angiography, validated on patients.");
    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Suggest keywords & criteria" }).click();
    const suggestions = page.getByRole("region", { name: /Suggestions/ });
    await expect(suggestions).toBeVisible({ timeout: 60_000 });
    await suggestions.getByRole("button", { name: "Accept all" }).click();
    await expect(page.getByRole("complementary", { name: "Field summary" })).toContainText(/Criteria\s*2 inclusions, 1 exclusion/);

    await page.getByRole("button", { name: "Next →" }).click();
    await expect(page.getByRole("heading", { name: /2 · Keywords & criteria/ })).toBeVisible();
    await expect(page.getByRole("status", { name: "Query for Europe PMC" })).toContainText("TITLE_ABS:");
    await page.getByRole("button", { name: "Next →" }).click();
    await page.getByRole("button", { name: "Preview search" }).click();
    const preview = page.getByRole("region", { name: "Search preview" });
    await expect(preview.locator(".preview-source").first()).toBeVisible({ timeout: 60_000 });
    await expect(preview).toContainText(/paper|failed/);
    await page.getByLabel("Change note").fill("first version");
    await page.getByRole("button", { name: "Create field" }).click();
    await expect(page.getByRole("heading", { name: "E2E plaque (v1)" })).toBeVisible();

    await page.getByRole("button", { name: "Test criteria" }).click();
    const results = page.getByRole("region", { name: "Criteria test" });
    await expect(results.getByRole("table")).toBeVisible({ timeout: 60_000 });

    await page.goto("/fields");
    await page.getByRole("link", { name: "Start run for E2E plaque" }).click();
    await page.getByLabel("Papers to screen").fill("3");
    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Start run" }).click();
    await expect(page.getByRole("status", { name: "Run progress" })).toContainText("done", { timeout: 120_000 });
    await page.locator("table.runs tbody tr").filter({ hasText: "E2E plaque" }).first().getByRole("link", { name: /^Papers of / }).click();
    await expect(page.getByRole("combobox", { name: "Run" })).toContainText("E2E plaque v1");
    await page.getByRole("button", { name: "Detailed", exact: true }).click(); // Simple is the default view
    await expect(page.locator("table.papers tbody tr").first()).toContainText(/all met|dropped by (incl|excl) \d|no single criterion decided/);

    const rows = page.locator("table.papers tbody tr");
    const titles = [await rows.nth(0).locator("[data-open-paper]").innerText(), await rows.nth(1).locator("[data-open-paper]").innerText()];
    await rows.nth(0).getByRole("checkbox").check();
    await rows.nth(1).getByRole("checkbox").check();
    await expect(page.getByRole("region", { name: "Selection" })).toContainText("2 selected");
    await page.getByRole("button", { name: "Save to library…" }).click();
    const dialog = page.getByRole("dialog", { name: "Save 2 papers to the library" });
    const collection = `E2E reading ${Date.now()}`; // the browser-test database outlives one run
    await dialog.getByLabel("New collection (optional)").fill(collection);
    await dialog.getByLabel("Tags", { exact: true }).fill("e2e");
    await dialog.getByLabel("Tags", { exact: true }).press("Enter");
    await dialog.getByRole("button", { name: "Save to library" }).click();
    // other tests may have saved one of these demo papers already: it is merged into the new collection
    await expect(page.getByRole("region", { name: "Notifications" })).toContainText(new RegExp(`Saved [12] papers? to ${collection}`));
    await expect(rows.nth(0).getByRole("link", { name: /In library · To read/ })).toBeVisible();

    await rows.nth(0).locator("[data-open-paper]").click();
    const drawer = page.getByRole("complementary", { name: "Paper details" });
    await drawer.getByRole("radio", { name: /Useful/ }).check();
    await expect(page.getByText("Marked useful")).toBeVisible();

    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Library" }).click();
    await page.getByLabel("Collection").selectOption({ label: `${collection} (2)` });
    const list = page.getByRole("list", { name: "Saved papers" });
    await expect(list.getByRole("listitem")).toHaveCount(2);
    for (const title of titles) await expect(list).toContainText(title.trim());
    await page.getByRole("group", { name: "Status" }).getByRole("button", { name: /Useful/ }).click();
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await list.getByRole("button").first().click();
    const pane = page.getByRole("complementary", { name: "Reading pane" });
    await expect(pane.getByRole("radio", { name: /Useful/ })).toBeChecked();
    await pane.getByRole("button", { name: /History/ }).click();
    await expect(pane).toContainText("changed the status from to read to useful");

    const href = await page.getByRole("link", { name: "Export CSV" }).getAttribute("href");
    expect(href).toContain("status=relevant");
    const response = await page.request.get(href!);
    expect(response.status()).toBe(200);
    expect(response.headers()["content-type"]).toContain("text/csv");
    expect(await response.text()).toContain(titles[0]!.trim().slice(0, 20));
  });

  test("keyboard shortcuts on Papers and Library", async ({ page }) => {
    await page.goto("/runs");
    await page.getByRole("row", { name: /toy/ }).getByRole("link", { name: /^Papers of / }).click();
    await expect(page.locator("table.papers tbody tr").first()).toBeVisible();
    await page.locator("h1").click();
    await page.keyboard.press("j");
    await expect(page.locator("[data-open-paper]").first()).toBeFocused();
    await page.keyboard.press("o");
    await expect(page.getByRole("complementary", { name: "Paper details" })).toBeVisible();
    await expect(page).toHaveURL(/paper=/);
    await page.keyboard.press("Escape");
    await page.locator("h1").click();
    await page.keyboard.press("?");
    await expect(page.getByRole("dialog", { name: "Papers shortcuts" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog")).toHaveCount(0);

    await page.goto("/library");
    const list = page.getByRole("list", { name: "Saved papers" });
    if (await list.count()) {
      await page.locator("h1").click();
      await page.keyboard.press("j");
      await page.keyboard.press("o");
      await expect(page.getByRole("complementary", { name: "Reading pane" })).toBeVisible();
    }
    await page.keyboard.press("/");
    await expect(page.getByRole("searchbox")).toBeFocused();
    await page.keyboard.type("jjj");
    await expect(page.getByRole("searchbox")).toHaveValue("jjj");
  });

  test("leaving the field editor with unsaved edits asks first", async ({ page }) => {
    await page.goto("/fields/new");
    await page.getByLabel("Name", { exact: true }).fill("Unsaved");
    page.once("dialog", (dialog) => void dialog.dismiss());
    await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Runs" }).click();
    await expect(page).toHaveURL(/\/fields\/new/);
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

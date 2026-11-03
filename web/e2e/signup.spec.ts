import { expect, test } from "@playwright/test";

// scripts/e2e_server.py opens sign-up for this domain (SIGNUP_DOMAINS)
const DOMAIN = "signup.example.org";

test.describe("sign-up", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("a new member signs up, saves a (fake) key and starts a demo search", async ({ page }) => {
    test.setTimeout(150_000);
    const email = `new-${Date.now()}@${DOMAIN}`;
    const password = "a long enough e2e password";
    await page.goto("/login");
    await page.getByRole("link", { name: "Create an account" }).click();
    await page.getByLabel("Work email").fill(email);
    await page.getByLabel("Name").fill("Nora New");
    await page.getByLabel(/^Password/).fill(password);
    await page.getByRole("button", { name: "Create account" }).click();
    await expect(page.getByRole("status")).toContainText("Sign in");
    await page.getByRole("link", { name: "Go to sign in" }).click();
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { name: "Sign in" })).toHaveCount(0);

    // a fake key: demo searches make no model calls, so it is never used
    await page.goto("/settings/keys");
    const models = page.getByRole("table", { name: "AI models" });
    await models.getByLabel("Anthropic (Claude) key").fill("sk-fake-e2e-key-1234");
    await models.getByRole("button", { name: "Save Anthropic (Claude) key" }).click();
    await expect(models.getByText(/Saved …1234/)).toBeVisible();
    await expect(page.getByText("sk-fake-e2e-key-1234")).toHaveCount(0);

    await page.goto("/screening");
    await page.getByRole("combobox", { name: "Topic", exact: true }).selectOption({ index: 1 });
    await page.getByLabel(/Papers to review/).fill("3");
    await page.getByLabel(/Demo mode/).check();
    await page.getByRole("button", { name: "Start a search" }).click();
    await expect(page.getByRole("status", { name: "Search progress" })).toContainText("Done", { timeout: 120_000 });
  });
});

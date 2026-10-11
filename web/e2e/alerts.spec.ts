import { expect, test } from "@playwright/test";

import { FEATURES } from "../src/config";
import { auth } from "./users";

test.describe("admin", () => {
  test.use({ storageState: auth("admin") });
  // Alerts are hidden (FEATURES.alerts); the code stays, so this spec comes back when they do
  test.skip(!FEATURES.alerts, "Alerts are hidden behind FEATURES.alerts");

  test("turns on a field alert, runs it now in demo mode and reads the digest in Alerts", async ({ page }) => {
    test.setTimeout(180_000);
    // a field of its own (an alert needs a field version), created through the API
    const me = await (await page.request.get("/api/v1/auth/me")).json();
    const created = await page.request.post("/api/v1/fields", {
      headers: { "X-CSRF-Token": me.csrf_token },
      data: { name: `E2E alert ${Date.now()}`, topic: "Deep learning for coronary CT angiography", sources: ["europepmc"], include: [{ text: "Uses CT angiography" }] },
    });
    expect(created.status()).toBe(201);
    const field = await created.json();
    await page.goto(`/topics/${field.id}`);
    const card = page.getByRole("complementary", { name: "Alert" });
    await expect(card).toBeVisible();
    await page.getByLabel(/Demo mode/).check();
    await card.getByLabel(/Repeat/).selectOption("daily");
    await card.getByLabel(/Max new papers/).fill("3");
    await card.getByRole("button", { name: "Save alert" }).click();
    await expect(card.getByRole("switch")).toBeChecked();
    await expect(card.getByText(/Every day at/)).toBeVisible();
    await card.getByRole("button", { name: "Run now (demo)" }).click();
    await expect(card.getByRole("link", { name: "started just now" })).toBeVisible();

    const nav = page.getByRole("navigation", { name: "Main" });
    await page.goto("/alerts");
    const digest = page.locator("article.digest-card").first();
    await expect(async () => {
      await page.reload();
      await expect(digest).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 150_000 });
    await expect(digest).toContainText(/\d+ found · \d+ already seen · \d+ new · \d+ worth reading/);
    await expect(nav.getByRole("link", { name: /^Alerts/ })).toBeVisible();
  });
});

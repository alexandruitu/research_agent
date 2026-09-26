import { expect, test as setup } from "@playwright/test";

import { auth, EMAIL, PASSWORD, ROLES } from "./users";

for (const role of ROLES) {
  setup(`sign in as ${role}`, async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Email").fill(EMAIL[role]);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    await page.context().storageState({ path: auth(role) });
  });
}

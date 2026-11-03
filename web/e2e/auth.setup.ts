import { expect, test as setup } from "@playwright/test";

import { auth, EMAIL, PASSWORD, ROLES } from "./users";

for (const role of ROLES) {
  setup(`sign in as ${role}`, async ({ page }) => {
    await page.goto("/");
    await page.getByLabel("Email").fill(EMAIL[role]);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("navigation", { name: "Main" })).toBeVisible();
    // the other specs start past the first-use guide (welcome.spec.ts covers it); the choice is in localStorage
    await page.goto("/topics");
    await page.getByRole("button", { name: "Hide this guide" }).click();
    await expect(page.getByRole("region", { name: /From a question to papers/ })).toHaveCount(0);
    await page.context().storageState({ path: auth(role) });
  });
}

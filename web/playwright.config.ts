import { defineConfig, devices } from "@playwright/test";

// override both when a dev server already holds the defaults (8000/4173)
const apiPort = process.env.E2E_API_PORT ?? "8000";
const webPort = process.env.E2E_WEB_PORT ?? "4173";

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: `http://127.0.0.1:${webPort}`, trace: "retain-on-failure" },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      dependencies: ["setup"],
      testIgnore: /auth\.setup\.ts/,
    },
  ],
  webServer: [
    {
      command: "python ../scripts/e2e_server.py",
      url: `http://127.0.0.1:${apiPort}/api/v1/health`,
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
      // the default is SIGKILL, which would leave the embedded postgres (and a pipeline child) running
      gracefulShutdown: { signal: "SIGTERM", timeout: 20_000 },
    },
    {
      command: "npm run build && npm run preview -- --strictPort --host 127.0.0.1",
      url: `http://127.0.0.1:${webPort}`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});

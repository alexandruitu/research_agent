import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: "http://127.0.0.1:4173", trace: "retain-on-failure" },
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
      url: "http://127.0.0.1:8000/api/v1/health",
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
      // the default is SIGKILL, which would leave the embedded postgres (and a pipeline child) running
      gracefulShutdown: { signal: "SIGTERM", timeout: 20_000 },
    },
    {
      command: "npm run build && npm run preview -- --strictPort --host 127.0.0.1",
      url: "http://127.0.0.1:4173",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// E2E_API_PORT / E2E_WEB_PORT let the browser tests run beside a dev server already on 8000/4173
const apiTarget = `http://127.0.0.1:${process.env.E2E_API_PORT ?? "8000"}`;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  preview: {
    port: Number(process.env.E2E_WEB_PORT ?? 4173),
    proxy: { "/api": { target: apiTarget, changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});

import react from "@vitejs/plugin-react";
import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";

// The two latin faces every page renders first: preloading them saves a round trip (the CSS would find them
// only after it loads). Hashed names are known only after bundling, so the links are added then.
const PRELOAD_FONTS = [
  /^assets\/newsreader-latin-opsz-normal-.*\.woff2$/,
  /^assets\/ibm-plex-sans-latin-400-normal-.*\.woff2$/,
];

function preloadFonts(): Plugin {
  return {
    name: "preload-fonts",
    apply: "build",
    transformIndexHtml(_html, ctx) {
      const files = Object.keys(ctx.bundle ?? {}).filter((file) =>
        PRELOAD_FONTS.some((font) => font.test(file)),
      );
      return files.map((file) => ({
        tag: "link",
        attrs: {
          rel: "preload",
          href: `/${file}`,
          as: "font",
          type: "font/woff2",
          crossorigin: "",
        },
        injectTo: "head" as const,
      }));
    },
  };
}

// E2E_API_PORT / E2E_WEB_PORT let the browser tests run beside a dev server already on 8000/4173
const apiTarget = `http://127.0.0.1:${process.env.E2E_API_PORT ?? "8000"}`;

export default defineConfig({
  plugins: [react(), preloadFonts()],
  build: {
    rollupOptions: {
      output: {
        // React, the router and TanStack Query change far less often than the app: their own chunk stays
        // cached in the browser across releases.
        manualChunks(id) {
          if (
            /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|@tanstack)[\\/]/.test(
              id,
            )
          ) {
            return "vendor";
          }
        },
      },
    },
  },
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

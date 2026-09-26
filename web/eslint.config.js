import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  globalIgnores(["dist", "playwright-report", "test-results", "src/api/schema.d.ts"]),
  js.configs.recommended,
  tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { "react-hooks": reactHooks },
    // The two classic hook rules. eslint-plugin-react-hooks 7's `recommended` preset also turns on the
    // React Compiler rules (purity, refs, set-state-in-effect, ...); opt in to those deliberately if wanted.
    rules: { "react-hooks/rules-of-hooks": "error", "react-hooks/exhaustive-deps": "warn" },
  },
  { files: ["**/*.{js,mjs}"], languageOptions: { globals: globals.node } },
);

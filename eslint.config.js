// ESLint flat config — the TypeScript/Vue counterpart to ruff on the Python side.
// ESLint catches bugs; Prettier owns formatting (see .prettierrc.json). Run with
// `pnpm lint` (report) / `pnpm lint:fix`, and `pnpm format` to reformat.
//
// eslint-plugin-vue is what makes this worth ESLint over a faster JS-only linter
// (biome/oxlint): those don't parse `.vue` single-file components.
import { defineConfig, globalIgnores } from "eslint/config";
import eslint from "@eslint/js";
import tseslint from "typescript-eslint";
import pluginVue from "eslint-plugin-vue";
import prettier from "eslint-config-prettier/flat";
import globals from "globals";

export default defineConfig(
  // Built output, deps, and the cloned reference packs — never our source.
  globalIgnores(["node_modules/**", "web/**", "dist/**", "reference/**"]),

  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  // `essential` = Vue's error-prevention rules only. The `recommended` tier piles on
  // attribute-formatting opinions (one attr per line, self-closing style, …) that a
  // formatter should own — same split as ruff lint vs `ruff format` on the Python side.
  ...pluginVue.configs["flat/essential"],

  {
    // vue-eslint-parser handles the SFC; hand its <script> blocks to the TS parser.
    files: ["**/*.vue"],
    languageOptions: {
      parserOptions: { parser: tseslint.parser },
    },
  },

  {
    // Frontend runs in the browser (ComfyUI's page), so browser globals are in scope.
    files: ["frontend/**/*.{ts,vue}"],
    languageOptions: {
      globals: { ...globals.browser },
    },
    rules: {
      // These components are only ever mounted by mountWidget/imported directly,
      // never registered globally where a one-word name could shadow an HTML
      // element. Short names (Button, Toggle) are deliberate here.
      "vue/multi-word-component-names": "off",
      // ComfyUI's frontend types are loose: node `output` records and JSON route
      // responses arrive untyped. Kept visible as a warning, not a hard failure.
      "@typescript-eslint/no-explicit-any": "warn",
    },
  },

  {
    // Build config runs in Node, not the browser.
    files: ["*.mts", "*.js"],
    languageOptions: {
      globals: { ...globals.node },
    },
  },

  {
    // Declaration shims: ambient `declare module` blocks legitimately need
    // otherwise-discouraged shapes.
    files: ["**/*.d.ts"],
    rules: {
      "@typescript-eslint/no-empty-object-type": "off",
      "@typescript-eslint/no-explicit-any": "off",
    },
  },

  // Last: switch off any lint rules that would fight Prettier's formatting.
  prettier,
);

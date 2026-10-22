import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    // The stylesheet is processed and injected into jsdom, so a test can ask the
    // document what a component actually resolves to rather than trusting the
    // class list it was given.
    css: true,
    // Generous, because these are whole-tree renders with real providers and
    // axe passes. At Vitest's 5s default a loaded machine failed a different
    // test on each run, with every assertion correct. A real hang still fails.
    testTimeout: 15_000,
  },
});

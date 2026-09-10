import { defineConfig } from "@playwright/test";

const baseURL = process.env.MNEMOS_RESPONSIVE_URL ?? "http://localhost:3001";

// Deterministic browser layout/interaction coverage. API-boundary fixtures keep
// viewport checks independent of model latency; e2e/ still exercises the real stack.
export default defineConfig({
  testDir: "./responsive",
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: "list",
  webServer: process.env.MNEMOS_RESPONSIVE_URL
    ? undefined
    : {
        command: "npm run dev -- --port 3001",
        url: baseURL,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "phone-320", use: { viewport: { width: 320, height: 640 }, isMobile: true, hasTouch: true } },
    { name: "phone-390", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
    { name: "tablet", use: { viewport: { width: 768, height: 1024 }, hasTouch: true } },
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
  ],
});

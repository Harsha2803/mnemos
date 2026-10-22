import { defineConfig } from "@playwright/test";

const baseURL = process.env.MNEMOS_RESPONSIVE_URL ?? "http://localhost:3001";

// The screenshot gallery (`npm run screens`). Same dev server and API-boundary
// fixture approach as the responsive suite, but every case writes a picture to
// docs/screens/ instead of asserting a layout. Clock, timezone, locale and
// motion are pinned so a picture changes only when the UI does.
export default defineConfig({
  testDir: "./screens",
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
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
    locale: "en-GB",
    timezoneId: "UTC",
    contextOptions: { reducedMotion: "reduce" },
    trace: "retain-on-failure",
  },
  projects: [
    { name: "phone-light", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, colorScheme: "light" } },
    { name: "phone-dark", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, colorScheme: "dark" } },
    { name: "desktop-light", use: { viewport: { width: 1440, height: 900 }, colorScheme: "light" } },
    { name: "desktop-dark", use: { viewport: { width: 1440, height: 900 }, colorScheme: "dark" } },
  ],
});

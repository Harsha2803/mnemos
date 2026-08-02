import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright, for the one flow that only a real browser can drive.
 *
 * Everything else in this app is tested in Vitest against jsdom, which is
 * faster and enough. This exists for the single thing jsdom cannot do at all:
 * **complete a login form served by Keycloak.** M3.4 drove `authorize` and
 * everything after the callback with `httpx`, and scripting the login page
 * itself ran into Keycloak 26's browser-session requirements — cookies set on
 * the auth page, a form action bound to that session — which is precisely what
 * a browser driver is for.
 *
 * It is deliberately **not** wired into `npm run test` or into CI. It needs
 * Postgres, Redis, Keycloak with the `mnemos` realm imported and a bootstrapped
 * org; a suite that silently passes when those are missing is worse than one
 * that is run on purpose. `e2e/auth.spec.ts` skips loudly when the stack is
 * down, and that skip was verified by stopping the API rather than assumed.
 */
export default defineConfig({
  testDir: "./e2e",
  // Serial. Every case in the file signs the same seeded admin in and out, and
  // signing out revokes the refresh family — two workers would revoke each
  // other's sessions and the failure would look like a backend bug.
  workers: 1,
  fullyParallel: false,
  // A real IdP round trip is several redirects and a Postgres write.
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.MNEMOS_E2E_WEB_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});

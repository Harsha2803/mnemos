import { expect, test, type Page } from "@playwright/test";

/**
 * A0 — signing in, staying signed in, and signing out, in a real browser
 * against a real Keycloak.
 *
 * This is the one thing the rest of the suite cannot reach. M3.4's live
 * evidence drove `authorize` and everything after the callback with `httpx`;
 * what it could not do is **fill in Keycloak's login form**, because Keycloak 26
 * binds that form to a browser session it establishes with cookies on the auth
 * page. TRACKER §3 recorded it as the milestone's one "could not verify". This
 * closes it.
 *
 * Every case here crosses four processes — the browser, Next, the API, Keycloak
 * — plus Postgres and Redis. When any of them is absent the file **skips**, and
 * says so; a suite that passes silently when the thing it tests is not running
 * is worse than no suite.
 */

const WEB = process.env.MNEMOS_E2E_WEB_URL ?? "http://localhost:3000";
const API = process.env.MNEMOS_E2E_API_URL ?? "http://localhost:8000";
const KEYCLOAK = process.env.MNEMOS_E2E_KEYCLOAK_URL ?? "http://localhost:8080";

/**
 * The org comes from `mnemosctl bootstrap`; the credential comes from the
 * **realm**, and they are two different things that both call themselves admin.
 *
 * `mnemos-dev-admin-password` (TRACKER §3 Environment) is the *internal*
 * provider's password for the local `app_user` row that bootstrap wrote. It has
 * nothing to do with Keycloak. What Keycloak's login form wants is the
 * credential in `deploy/keycloak/mnemos-realm.json`, which is `admin`. Both are
 * dev-stack credentials in the same class as Keycloak's own `admin`/`admin`,
 * and neither is ever to be reused anywhere real.
 */
const ORG = process.env.MNEMOS_E2E_ORG ?? "mnemos";
const EMAIL = process.env.MNEMOS_E2E_EMAIL ?? "admin@mnemos.local";
const PASSWORD = process.env.MNEMOS_E2E_PASSWORD ?? "admin";

async function reachable(url: string): Promise<boolean> {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(4000) });
    return response.ok;
  } catch {
    return false;
  }
}

/** Which of the four is missing, named — so a skip is a diagnosis, not a shrug. */
async function missingServices(): Promise<string[]> {
  const checks: Array<[string, string]> = [
    ["web", WEB],
    ["api", `${API}/readyz`],
    ["keycloak", `${KEYCLOAK}/realms/mnemos/.well-known/openid-configuration`],
  ];
  const results = await Promise.all(checks.map(([, url]) => reachable(url)));
  return checks.filter((_, index) => !results[index]).map(([name]) => name);
}

test.beforeAll(async () => {
  const missing = await missingServices();
  test.skip(
    missing.length > 0,
    `the stack is not up: ${missing.join(", ")} unreachable. ` +
      "Run `docker compose up -d`, then `mnemosctl bootstrap`.",
  );
});

async function signIn(page: Page): Promise<void> {
  await page.getByLabel("Workspace").fill(ORG);
  await page.getByRole("button", { name: /continue with keycloak/i }).click();

  // Keycloak's own login page, on its own origin. The field names are the
  // realm's, not ours — this is the boundary the test exists to cross.
  await page.waitForURL(new RegExp(`^${KEYCLOAK}/realms/mnemos/`));
  await page.locator("#username").fill(EMAIL);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#kc-login").click();
}

test("test_a_seeded_admin_signs_in_through_keycloak_and_lands_on_the_shell", async ({ page }) => {
  await page.goto(`${WEB}/signin`);
  await signIn(page);

  // Back on our origin, through the callback, with the shell rendered.
  await page.waitForURL(`${WEB}/`);
  await expect(page.getByRole("navigation", { name: "Workspace" })).toBeVisible();

  // The sidebar names the real user and the real tenant — both from
  // `GET /auth/me`, neither from the token.
  await expect(page.getByText(EMAIL)).toBeVisible();
  await expect(page.getByText(ORG, { exact: true })).toBeVisible();
});

test("test_no_credential_ever_appears_in_a_url_or_in_web_storage", async ({ page }) => {
  const visited: string[] = [];
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) visited.push(frame.url());
  });

  await page.goto(`${WEB}/signin`);
  await signIn(page);
  await page.waitForURL(`${WEB}/`);

  // The callback redirects rather than rendering a token, so no URL in the
  // whole round trip carries one — not in history, not in a `Referer`, not in
  // whatever proxy log sat in the middle.
  for (const url of visited) {
    expect(url).not.toContain("access_token");
    expect(url).not.toMatch(/eyJ[A-Za-z0-9_-]{8,}\./);
  }

  // And nothing that looks like a JWT reached web storage, in a real browser
  // rather than in jsdom.
  const stored = await page.evaluate(() =>
    JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
  );
  expect(stored).not.toMatch(/eyJ[A-Za-z0-9_-]{8,}\./);

  // The refresh token *is* there — as a cookie no script can read.
  const cookies = await page.context().cookies();
  const refresh = cookies.find((cookie) => cookie.name === "mnemos_refresh");
  expect(refresh?.httpOnly).toBe(true);
});

test("test_a_reload_keeps_the_user_signed_in", async ({ page }) => {
  await page.goto(`${WEB}/signin`);
  await signIn(page);
  await page.waitForURL(`${WEB}/`);

  // The access token is in a module variable and does not survive this. What
  // survives is the `httpOnly` cookie, and the app's first act on load is to
  // exchange it — which is the whole reason a reload is not a sign-out.
  await page.reload();

  await expect(page.getByText(EMAIL)).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Workspace" })).toBeVisible();
});

test("test_signing_out_returns_to_signin_and_a_protected_route_bounces_back", async ({ page }) => {
  await page.goto(`${WEB}/signin`);
  await signIn(page);
  await page.waitForURL(`${WEB}/`);

  await page.getByRole("button", { name: `Sign out of ${ORG}` }).click();
  await page.waitForURL(new RegExp(`^${WEB}/signin`));

  // The revocation was real: navigating back to a protected route bounces to
  // sign-in rather than restoring the session from the cookie, because the
  // cookie is gone and its whole rotation chain is revoked.
  await page.goto(`${WEB}/`);
  await page.waitForURL(new RegExp(`^${WEB}/signin`));
  await expect(page.getByRole("button", { name: /continue with keycloak/i })).toBeVisible();
});

test("test_an_unknown_workspace_returns_to_signin_with_the_same_message", async ({ page }) => {
  await page.goto(`${WEB}/signin`);
  await page.getByLabel("Workspace").fill("no-such-workspace-here");
  await page.getByRole("button", { name: /continue with keycloak/i }).click();

  // Not a JSON 401 rendered at a person, and not a message that says the
  // workspace does not exist — which would be a tenant-enumeration oracle
  // reachable by anybody with a browser.
  await page.waitForURL(new RegExp(`^${WEB}/signin\\?error=`));
  // By id, not by role: Next's own route announcer is also `role="alert"`, and
  // a strict locator resolving to two elements is a failure rather than a
  // choice.
  const message = await page.locator("#signin-error").textContent();
  expect(message).toBeTruthy();
  expect(message?.toLowerCase()).not.toContain("no such");
  expect(message?.toLowerCase()).not.toContain("not found");
});

test("test_an_unauthenticated_visit_to_a_protected_route_redirects_to_signin", async ({ page }) => {
  await page.goto(`${WEB}/`);

  await page.waitForURL(new RegExp(`^${WEB}/signin`));
  await expect(page.getByRole("button", { name: /continue with keycloak/i })).toBeVisible();
});

test("test_the_api_refuses_a_protected_route_without_a_token", async ({ request }) => {
  // The control the client-side redirect above is *not*. Hiding a route in the
  // browser is a courtesy; this is the boundary that actually holds, and it is
  // asserted here in the same run so the two cannot be confused for each other.
  const response = await request.get(`${API}/api/v1/auth/me`, { failOnStatusCode: false });

  expect(response.status()).toBe(401);
  expect(await response.json()).toEqual({
    error: { code: "unauthenticated", message: "authentication failed" },
  });
});

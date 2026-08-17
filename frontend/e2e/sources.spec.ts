import { expect, test, type Page } from "@playwright/test";

/**
 * `B1` deliverable 5 — connect a source, browse it, ingest an item, and
 * watch it move through `queued -> running -> succeeded` **live**, over the
 * WebSocket gateway deliverable 3 authenticated, in a real browser against
 * the real stack.
 *
 * The local-filesystem connector, not S3 or HTTP, is what this spec drives —
 * TRACKER §5 deliverable 5's own reasoning: it is the one connector kind a
 * CI runner can exercise for free, no bucket or live URL required. The
 * fixture it registers against is `e2e-fixtures/sources/`, bind-mounted into
 * both the `api` and `worker` containers at `/fixtures/sources` (docker-
 * compose.yml), the one path `MNEMOS_LOCAL_FS_ALLOWED_ROOTS` opts in.
 *
 * Same shape as `auth.spec.ts`/`knowledge.spec.ts`/`nl2sql.spec.ts`: skips
 * loudly, naming what is missing.
 */

const WEB = process.env.MNEMOS_E2E_WEB_URL ?? "http://localhost:3000";
const API = process.env.MNEMOS_E2E_API_URL ?? "http://localhost:8000";
const KEYCLOAK = process.env.MNEMOS_E2E_KEYCLOAK_URL ?? "http://localhost:8080";

const ORG = process.env.MNEMOS_E2E_ORG ?? "mnemos";
// `analyst`, not `admin` — see TRACKER §4 item 40.
const EMAIL = process.env.MNEMOS_E2E_EMAIL ?? "analyst@mnemos.local";
const PASSWORD = process.env.MNEMOS_E2E_PASSWORD ?? "analyst";

async function missingServices(): Promise<string[]> {
  const missing: string[] = [];
  const web = await fetch(WEB, { signal: AbortSignal.timeout(4000) }).catch(() => null);
  if (web === null || !web.ok) missing.push("web");

  const realm = await fetch(`${KEYCLOAK}/realms/mnemos/.well-known/openid-configuration`, {
    signal: AbortSignal.timeout(4000),
  }).catch(() => null);
  if (realm === null || !realm.ok) missing.push("keycloak");

  const ready = await fetch(`${API}/readyz`, { signal: AbortSignal.timeout(4000) }).catch(
    () => null,
  );
  if (ready === null) {
    missing.push("api");
  } else {
    const body: unknown = await ready.json().catch(() => null);
    const checks =
      typeof body === "object" && body !== null
        ? (body as { checks?: Record<string, string> }).checks
        : undefined;
    for (const name of ["postgres", "redis"] as const) {
      if (checks?.[name] !== "ok") missing.push(name);
    }
  }
  return missing;
}

test.beforeAll(async () => {
  const missing = await missingServices();
  test.skip(
    missing.length > 0,
    `the stack is not up: ${missing.join(", ")}. Run \`docker compose up -d --build\`.`,
  );
});

async function signIn(page: Page): Promise<void> {
  await page.goto(`${WEB}/signin`);
  await page.getByLabel("Workspace").fill(ORG);
  await page.getByRole("button", { name: /continue with keycloak/i }).click();
  await page.waitForURL(new RegExp(`^${KEYCLOAK}/realms/mnemos/`));
  await page.locator("#username").fill(EMAIL);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#kc-login").click();
  await page.waitForURL(`${WEB}/`);
}

function nav(page: Page) {
  return page.getByRole("navigation", { name: "Workspace" });
}

test("test_you_can_connect_a_local_fs_source_ingest_an_item_and_watch_it_succeed_live", async ({
  page,
}) => {
  // Unique per run: `content_source` has a `(org_id, slug)` uniqueness
  // constraint, and a fixed slug would collide with the previous run's row —
  // there is no delete/unregister in this deliverable's scope (TRACKER §5's
  // "explicitly not B1" list), so the slug itself is what stays unique
  // instead. The fixture file the slug points at is the same static one
  // every run — only the registration is per-run.
  const runId = Date.now().toString(36);
  const slug = `e2e-fixtures-${runId}`;

  await signIn(page);

  await nav(page).getByRole("link", { name: "Sources", exact: true }).click();
  await page.waitForURL(new RegExp(`^${WEB}/sources`));

  await page.locator("#source-name").fill(`E2E fixtures ${runId}`);
  await page.locator("#source-slug").fill(slug);
  // "Local filesystem directory" is already the form's default `kind`.
  await page.locator("#source-root").fill("/fixtures/sources");
  await page.getByRole("button", { name: "Register source" }).click();

  const sourceButton = page.getByRole("button", { name: new RegExp(slug) });
  await expect(sourceButton).toBeVisible({ timeout: 15_000 });
  await sourceButton.click();

  const row = page.getByRole("row").filter({ hasText: "handbook.txt" });
  await expect(row).toBeVisible({ timeout: 15_000 });
  await row.getByLabel("Select handbook.txt").check();

  await page.getByRole("button", { name: /Ingest 1/ }).click();

  const feed = page.getByRole("list", { name: "Ingestion activity" });
  const feedRow = feed.getByRole("listitem").filter({ hasText: "handbook.txt" });

  // Optimistic first: the UI's own "ingest requested" state, before any
  // socket message has necessarily arrived.
  await expect(feedRow).toContainText(/Queued|Running|Succeeded/, { timeout: 15_000 });

  // Then live, over the authenticated WebSocket, with no page reload: the
  // worker actually claims the job, extracts/chunks/embeds the fixture file,
  // and the gateway relays every transition to this same open connection.
  await expect(feedRow).toContainText("Succeeded", { timeout: 60_000 });
});

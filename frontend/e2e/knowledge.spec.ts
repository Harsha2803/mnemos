import { expect, test, type Page } from "@playwright/test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/**
 * `A2` — upload a document and ask about it, in a real browser against the
 * real stack: MinIO holding the bytes, pgvector holding the embeddings, and a
 * real model producing an answer that cites what it read.
 *
 * Skips loudly and names what is missing, same shape as `auth.spec.ts` and
 * `chat.spec.ts`.
 */

const WEB = process.env.MNEMOS_E2E_WEB_URL ?? "http://localhost:3000";
const API = process.env.MNEMOS_E2E_API_URL ?? "http://localhost:8000";
const KEYCLOAK = process.env.MNEMOS_E2E_KEYCLOAK_URL ?? "http://localhost:8080";

// `analyst`, not `admin` — see TRACKER §4 item 40.
const ORG = process.env.MNEMOS_E2E_ORG ?? "mnemos";
const EMAIL = process.env.MNEMOS_E2E_EMAIL ?? "analyst@mnemos.local";
const PASSWORD = process.env.MNEMOS_E2E_PASSWORD ?? "analyst";

/**
 * Unique per run, and the uniqueness is load-bearing rather than cosmetic.
 * Upload is content-addressed: identical bytes return the *existing*
 * document instead of a new one, so a fixed fixture would silently reuse the
 * previous run's row and the test would stop proving that ingestion works.
 * A run marker in the text also keeps the title unambiguous when a developer's
 * stack has accumulated documents from earlier runs.
 */
function handbook(runId: string): string {
  return `Mnemos E2E Handbook (run ${runId})

Leave and time off

Carry-over of unused discretionary leave into the following calendar year is
capped at five working days. Any balance above that cap is forfeited on the
thirty-first of December.
`;
}

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
    for (const name of ["postgres", "redis", "objectstore"] as const) {
      if (checks?.[name] !== "ok") missing.push(name);
    }
    if (checks?.ollama !== "ok") {
      missing.push("ollama (model not pulled — docker compose exec ollama ollama pull qwen2.5:3b-instruct)");
    }
  }
  return missing;
}

test.beforeAll(async () => {
  const missing = await missingServices();
  test.skip(
    missing.length > 0,
    `the stack is not up: ${missing.join(", ")}. Run \`docker compose up -d\`, then ` +
      "`mnemosctl bootstrap`.",
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

/** The sidebar's own nav — the session list also contains `/chat/...` links. */
function nav(page: Page) {
  return page.getByRole("navigation", { name: "Workspace" });
}

test("test_you_can_upload_a_document_ask_about_it_and_click_the_citation", async ({ page }) => {
  const runId = Date.now().toString(36);
  const filename = `handbook-${runId}.txt`;
  const directory = mkdtempSync(join(tmpdir(), "mnemos-e2e-"));
  const path = join(directory, filename);
  writeFileSync(path, handbook(runId));

  await signIn(page);

  await nav(page).getByRole("link", { name: "Knowledge", exact: true }).click();
  await page.waitForURL(new RegExp(`^${WEB}/knowledge`));
  await page.setInputFiles('input[aria-label="Upload a document"]', path);

  // Extracted, chunked and embedded — the row says how many passages, which
  // is a claim about the pipeline rather than about the upload alone.
  const row = page.getByRole("listitem").filter({ hasText: filename });
  await expect(row).toBeVisible({ timeout: 60_000 });
  await expect(row).toContainText(/\d+ passages/);

  await nav(page).getByRole("link", { name: "Chat", exact: true }).click();
  await page.waitForURL(new RegExp(`^${WEB}/chat`));
  await page.getByRole("main").getByRole("button", { name: "New chat" }).click();
  await page.waitForURL(new RegExp(`^${WEB}/chat/`));

  await page.getByRole("radio", { name: "Use documents" }).click();
  const composer = page.getByRole("textbox", { name: "Message" });
  await composer.fill("How many days of unused leave can I carry over?");
  await composer.press("Enter");

  await expect(page.getByRole("button", { name: "Send message" })).toBeVisible({
    timeout: 90_000,
  });

  // The citation is a real button, and clicking it fills the inspector with
  // the passage — the "click into" half of the milestone's sentence.
  const marker = page.getByRole("button", { name: /Show source \d/ }).first();
  await expect(marker).toBeVisible({ timeout: 30_000 });
  await marker.click();

  const inspector = page.getByRole("complementary", { name: "Context inspector" });
  await expect(inspector).toContainText("five working days");
  await expect(inspector).toContainText(/Characters \d+–\d+/);

  // Clean up after itself. A suite that leaves a document behind on every run
  // grows the developer's library without bound, and the delete path is worth
  // exercising here anyway — including the confirmation that names the file.
  await nav(page).getByRole("link", { name: "Knowledge", exact: true }).click();
  await page.waitForURL(new RegExp(`^${WEB}/knowledge`));
  await page.getByRole("button", { name: `Delete ${filename}` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect(page.getByRole("listitem").filter({ hasText: filename })).toHaveCount(0);
});

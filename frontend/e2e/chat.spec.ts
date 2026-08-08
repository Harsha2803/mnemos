import { expect, test, type Page } from "@playwright/test";

/**
 * `A1` — talk to it, in a real browser against the real stack: Next, the API,
 * Ollama, Postgres and Redis all running, a real token stream arriving over
 * SSE rather than a stub.
 *
 * Same shape as `auth.spec.ts`: skips loudly, naming what is missing, rather
 * than failing with a timeout that could be anything. The one thing specific
 * to this file is the model — `GET /readyz` now reports `ollama` (the `A1`
 * gateway commit), so "the stack is up" already implies the model is pulled;
 * this file still names it explicitly in the skip reason, because "ollama
 * unreachable" and "model not pulled" are different fixes and a skip that
 * only said the first would send the next person to restart a container that
 * was never the problem.
 */

const WEB = process.env.MNEMOS_E2E_WEB_URL ?? "http://localhost:3000";
const API = process.env.MNEMOS_E2E_API_URL ?? "http://localhost:8000";
const KEYCLOAK = process.env.MNEMOS_E2E_KEYCLOAK_URL ?? "http://localhost:8080";

const ORG = process.env.MNEMOS_E2E_ORG ?? "mnemos";
// Deliberately **not** admin@mnemos.local, unlike auth.spec.ts. `mnemosctl
// bootstrap` creates that email as an *internal*-provider user; signing in
// through Keycloak as the realm user of the same name collides on email and
// is correctly denied (M3.4's JIT-provisioning rule — matching is on
// `external_subject`, never on email). TRACKER §4 item 38 records that A0's
// browser evidence dodged this with a throwaway org; `analyst@mnemos.local`
// has no bootstrap-created counterpart, so it JIT-provisions cleanly against
// the stack's real, persistent "mnemos" org, and chat needs no permission the
// analyst role would be missing.
const EMAIL = process.env.MNEMOS_E2E_EMAIL ?? "analyst@mnemos.local";
const PASSWORD = process.env.MNEMOS_E2E_PASSWORD ?? "analyst";

async function reachable(url: string): Promise<boolean> {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(4000) });
    return response.ok;
  } catch {
    return false;
  }
}

async function missingServices(): Promise<string[]> {
  const missing: string[] = [];
  if (!(await reachable(WEB))) missing.push("web");
  if (!(await reachable(`${KEYCLOAK}/realms/mnemos/.well-known/openid-configuration`))) {
    missing.push("keycloak");
  }

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
    if (checks?.postgres !== "ok") missing.push("postgres");
    if (checks?.redis !== "ok") missing.push("redis");
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

test("test_you_can_ask_mnemos_a_question_and_watch_it_stream_and_persist", async ({ page }) => {
  await signIn(page);

  await page.getByRole("link", { name: "Chat" }).click();
  await page.waitForURL(new RegExp(`^${WEB}/chat`));
  // Several "New chat" controls exist at once (the sidebar's icon button, its
  // own empty state, and this page's) — the main region's is unambiguous.
  await page.getByRole("main").getByRole("button", { name: "New chat" }).click();
  await page.waitForURL(new RegExp(`^${WEB}/chat/`));

  const composer = page.getByRole("textbox", { name: "Message" });
  await composer.fill("Say the single word: hello");
  await composer.press("Enter");

  // The assistant bubble exists before it has any text — the "never a
  // spinner over a blank region" rule, observed rather than only unit-tested.
  await expect(page.getByText("Thinking…")).toBeVisible();

  // Streaming completed: the Stop control reverts to Send, and there is now
  // more than one visible message.
  await expect(page.getByRole("button", { name: "Send message" })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("You").first()).toBeVisible();
  await expect(page.getByText("Mnemos").first()).toBeVisible();

  const sessionUrl = page.url();

  await page.reload();

  // Still there — this is the "a conversation that is still there tomorrow"
  // half of the sentence, not merely "the stream worked".
  await expect(page).toHaveURL(sessionUrl);
  await expect(page.getByText("Say the single word: hello")).toBeVisible();
});

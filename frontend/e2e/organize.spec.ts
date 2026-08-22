import { expect, test, type Page } from "@playwright/test";

/**
 * `C3` — conversation product depth, end to end in one authenticated session:
 * folders, bookmarks, feedback and history search (deliverables 1-4). Mirrors
 * `chat.spec.ts`'s structure: `missingServices()` skip guard, role/label-based
 * assertions only, no `data-testid`, an explicit reload to prove persistence.
 *
 * Audit (deliverable 5) is **not** exercised here as a full admin walkthrough.
 * `admin@mnemos.local` cannot complete an OIDC sign-in in this stack — it is
 * an internal-auth bootstrap user, not a real Keycloak identity, and signing
 * in as it correctly triggers the same email-collision guard `chat.spec.ts`
 * already routes around by using `analyst@mnemos.local` instead (see TRACKER
 * §5 deliverable 5's dated note for how this was found and why it is out of
 * scope to fix here). A second small test below covers the one thing that
 * *can* be proven with the account this file already signs in as: a non-admin
 * gets the specific 403 message, not a generic error or a silent empty page.
 * The admin-sees-the-table path was verified manually against a temporary,
 * reverted role grant — also recorded in that same dated note.
 */

const WEB = process.env.MNEMOS_E2E_WEB_URL ?? "http://localhost:3000";
const API = process.env.MNEMOS_E2E_API_URL ?? "http://localhost:8000";
const KEYCLOAK = process.env.MNEMOS_E2E_KEYCLOAK_URL ?? "http://localhost:8080";

const ORG = process.env.MNEMOS_E2E_ORG ?? "mnemos";
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

test("test_you_can_organize_bookmark_rate_and_find_a_conversation", async ({ page }) => {
  const runId = Date.now().toString(36);
  const folderAName = `E2E ${runId} A`;
  const folderBName = `E2E ${runId} B`;
  const word = `zephyrquokka${runId}`;

  await signIn(page);
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", {
    name: "Chat",
    exact: true,
  }).click();
  await page.waitForURL(new RegExp(`^${WEB}/chat`));

  const sidebar = page.getByRole("navigation", { name: "Workspace" });

  // --- Deliverable 1: two folders exist before anything is filed into them.
  await sidebar.getByRole("button", { name: "New folder" }).click();
  await sidebar.getByLabel("Folder name").fill(folderAName);
  await page.keyboard.press("Enter");
  await expect(sidebar.getByText(folderAName, { exact: true })).toBeVisible();

  await sidebar.getByRole("button", { name: "New folder" }).click();
  await sidebar.getByLabel("Folder name").fill(folderBName);
  await page.keyboard.press("Enter");
  await expect(sidebar.getByText(folderBName, { exact: true })).toBeVisible();
  // Folder B stays empty for the whole test — it must still be listed, not
  // hidden, so a just-created folder never looks like it silently vanished.
  const folderBHeading = sidebar.getByText(folderBName, { exact: true });
  const folderBRow = folderBHeading.locator("xpath=ancestor::li[1]");
  await expect(folderBRow.locator("xpath=following-sibling::li[1]")).toContainText(
    "No conversations here yet.",
  );

  // --- A real conversation to organize, bookmark and rate.
  await sidebar.getByRole("button", { name: "New chat" }).click();
  await page.waitForURL(new RegExp(`^${WEB}/chat/`));
  const sessionId = page.url().split("/chat/")[1];

  const composer = page.getByRole("textbox", { name: "Message" });
  await composer.fill(`Please remember the word ${word} for later.`);
  await composer.press("Enter");
  await expect(page.getByText("Thinking…")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send message" })).toBeVisible({
    timeout: 30_000,
  });

  // --- Deliverable 2: bookmark the assistant's reply.
  await page.getByRole("button", { name: "Bookmark this answer" }).click();
  await expect(page.getByRole("button", { name: "Remove bookmark" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  const assistantBubble = page
    .locator('div[id^="message-"]')
    .filter({ has: page.getByRole("button", { name: "Remove bookmark" }) });
  const bubbleId = await assistantBubble.getAttribute("id");
  const messageId = bubbleId?.replace("message-", "") ?? "";
  expect(messageId).not.toBe("");

  // --- Deliverable 3: rate it down, with a comment.
  await page.getByRole("button", { name: "Bad answer" }).click();
  await expect(page.getByRole("button", { name: "Remove rating" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.getByLabel("What went wrong? (optional)").fill(`noted via e2e ${runId}`);
  await page.keyboard.press("Enter");
  await expect(page.getByLabel("What went wrong? (optional)")).toHaveCount(0);

  // --- Deliverable 1: file this session into Folder A.
  const sessionRow = sidebar.locator("li").filter({
    has: page.locator(`a[href="/chat/${sessionId}"]`),
  });
  await sessionRow.getByRole("button", { name: /^Move .* to a folder$/ }).click();
  // Not scoped to `sessionRow`: entering "moving" state replaces this row's
  // own `<a href>` with the `<select>`, so a locator that filters on that
  // href no longer matches its own row's children the instant it needs to —
  // there is only ever one row moving at a time, so the sidebar's one
  // combobox is unambiguous.
  await sidebar.getByRole("combobox").selectOption({ label: folderAName });

  const folderAHeading = sidebar.getByText(folderAName, { exact: true });
  const folderARow = folderAHeading.locator("xpath=ancestor::li[1]");
  await expect(
    folderARow.locator("xpath=following-sibling::li[1]").locator(`a[href="/chat/${sessionId}"]`),
  ).toBeVisible();

  // --- Renaming while filed does not un-file it.
  await sessionRow.getByRole("button", { name: /^Rename / }).click();
  // Same reason as the move step above: editing state replaces the row's
  // own `<a href>` with the rename input, so this is unscoped too.
  await sidebar.getByLabel("Conversation name").fill(`Renamed ${runId}`);
  await page.keyboard.press("Enter");
  await expect(
    folderARow.locator("xpath=following-sibling::li[1]").locator(`a[href="/chat/${sessionId}"]`),
  ).toContainText(`Renamed ${runId}`);

  // --- Reload: folder grouping and the rename both survive.
  await page.reload();
  await expect(
    sidebar
      .getByText(folderAName, { exact: true })
      .locator("xpath=ancestor::li[1]")
      .locator("xpath=following-sibling::li[1]")
      .locator(`a[href="/chat/${sessionId}"]`),
  ).toContainText(`Renamed ${runId}`);

  // --- Deliverable 2 continued: the bookmark shows up on its own page and
  // links back to this exact message, not just this session.
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", {
    name: "Bookmarks",
    exact: true,
  }).click();
  await page.waitForURL(`${WEB}/bookmarks`);
  const bookmarkLink = page.locator(`a[href="/chat/${sessionId}#message-${messageId}"]`);
  await expect(bookmarkLink).toBeVisible();
  await bookmarkLink.locator("xpath=ancestor::div[contains(@class,'list-row')][1]")
    .getByRole("button")
    .click();
  await expect(bookmarkLink).toHaveCount(0);

  // --- Deliverable 4: history search finds this conversation by content,
  // not just by whatever the sidebar happens to be showing.
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", {
    name: "Chat",
    exact: true,
  }).click();
  await page.waitForURL(new RegExp(`^${WEB}/chat`));
  await page.getByPlaceholder("Search conversations").fill(word);
  await expect(
    page.getByRole("list", { name: "Search results" }).locator(`a[href="/chat/${sessionId}"]`),
  ).toBeVisible({ timeout: 10_000 });
  await page.getByPlaceholder("Search conversations").fill("");

  // --- Deliverable 1 continued: deleting a folder un-files its session
  // rather than deleting it, and leaves the other folder alone.
  await sidebar.getByRole("button", { name: `Delete ${folderAName}` }).click();
  await expect(page.getByText("Its conversations are not deleted")).toBeVisible();
  await page.getByRole("button", { name: "Delete" }).click();
  await expect(sidebar.getByText(folderAName, { exact: true })).toHaveCount(0);
  await expect(sidebar.locator(`a[href="/chat/${sessionId}"]`)).toBeVisible();
  await expect(sidebar.getByText(folderBName, { exact: true })).toBeVisible();
});

test("test_a_non_admin_sees_the_specific_audit_refusal_not_a_generic_error", async ({ page }) => {
  await signIn(page);
  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", {
    name: "Audit log",
    exact: true,
  }).click();
  await page.waitForURL(`${WEB}/audit`);
  await expect(page.getByText("Only administrators can view the audit log")).toBeVisible();
});

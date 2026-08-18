import { expect, test, type Page } from "@playwright/test";

const WEB = process.env.MNEMOS_E2E_WEB_URL ?? "http://localhost:3000";
const API = process.env.MNEMOS_E2E_API_URL ?? "http://localhost:8000";
const KEYCLOAK = process.env.MNEMOS_E2E_KEYCLOAK_URL ?? "http://localhost:8080";
const ORG = process.env.MNEMOS_E2E_ORG ?? "mnemos";
const EMAIL = process.env.MNEMOS_E2E_EMAIL ?? "analyst@mnemos.local";
const PASSWORD = process.env.MNEMOS_E2E_PASSWORD ?? "analyst";

async function reachable(url: string): Promise<boolean> {
  try {
    return (await fetch(url, { signal: AbortSignal.timeout(4000) })).ok;
  } catch {
    return false;
  }
}

test.beforeAll(async () => {
  const missing: string[] = [];
  if (!(await reachable(WEB))) missing.push("web");
  if (!(await reachable(`${API}/readyz`))) missing.push("api");
  if (!(await reachable(`${KEYCLOAK}/realms/mnemos/.well-known/openid-configuration`))) {
    missing.push("keycloak");
  }
  test.skip(missing.length > 0, `the stack is not up: ${missing.join(", ")}`);
});

async function signIn(page: Page): Promise<void> {
  await page.goto(`${WEB}/signin`);
  await page.getByLabel("Workspace").fill(ORG);
  await page.getByRole("button", { name: /continue with keycloak/i }).click();
  await page.locator("#username").fill(EMAIL);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#kc-login").click();
  await page.waitForURL(`${WEB}/`);
}

test("test_memory_lifecycle_and_persisted_bundle_are_inspectable", async ({ page }) => {
  await signIn(page);
  const subjectRef = `employee:c4-${Date.now()}`;

  await page.getByRole("link", { name: "Memory" }).click();
  await page.getByLabel("Subject reference").first().fill(subjectRef);
  await page.getByLabel("Subject name").fill("C4 Demo");
  await page.getByLabel("Predicate").fill("home_hub");
  await page.getByRole("textbox", { name: "Claim", exact: true }).fill("London");
  await page.getByRole("button", { name: "Save claim" }).click();
  await expect(page.getByRole("status")).toContainText("Saved C4 Demo");

  const london = page.getByRole("listitem").filter({ hasText: "London" });
  await london.getByRole("button", { name: "Supersede" }).click();
  await page.getByRole("textbox", { name: "Claim", exact: true }).fill("Berlin");
  await page.getByRole("button", { name: "Create replacement" }).click();
  await expect(page.getByRole("status")).toContainText("Superseded with C4 Demo");
  await expect(page.getByText("Berlin").first()).toBeVisible();
  await expect(page.getByText("London").first()).toBeVisible();

  await page.getByLabel("Subject reference").first().fill(subjectRef);
  await page.getByLabel("Subject name").fill("C4 Demo");
  await page.getByLabel("Predicate").fill("temporary_note");
  await page.getByLabel("Claim kind").selectOption("observation");
  await page
    .getByRole("textbox", { name: "Claim", exact: true })
    .fill("Remove this temporary observation");
  await page.getByRole("button", { name: "Save claim" }).click();
  const temporary = page
    .getByRole("listitem")
    .filter({ hasText: "Remove this temporary observation" });
  await temporary.getByRole("button", { name: "Retract" }).click();
  await expect(page.getByRole("status")).toContainText("Claim retracted");

  await page.getByRole("link", { name: "Chat", exact: true }).click();
  await page.getByRole("main").getByRole("button", { name: "New chat" }).click();
  const composer = page.getByRole("textbox", { name: "Message" });
  await composer.fill("What durable context do you have about the C4 Demo employee?");
  await composer.press("Enter");
  await expect(page.getByText("Thinking…")).toBeVisible();
  await expect(page.getByRole("button", { name: "Send message" })).toBeVisible({
    timeout: 30_000,
  });
  await page.reload();

  await page.getByRole("button", { name: "Inspect answer" }).last().click();
  await page.getByRole("button", { name: "Bundle" }).click();
  await expect(page.getByRole("heading", { name: "Hard token budget" })).toBeVisible();
  await expect(page.getByText(/^Admitted · \d+$/)).toBeVisible();
  await expect(page.getByText(/^Excluded · \d+$/)).toBeVisible();
  await page.getByText("Compiled prompt").click();
  await expect(page.getByText("[QUESTION]", { exact: false })).toBeVisible();
});

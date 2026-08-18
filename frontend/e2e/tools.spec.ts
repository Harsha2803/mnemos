import { expect, test, type Page } from "@playwright/test";

/** B3 — register, discover, grant, approve, and run one local MCP tool. */

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
  if (!(await reachable("http://localhost:8100/healthz"))) missing.push("demo-mcp");
  test.skip(
    missing.length > 0,
    `the B3 stack is not up: ${missing.join(", ")}. Run \`docker compose up -d --build\`.`,
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

test("test_you_can_register_discover_approve_and_run_one_local_tool", async ({ page }) => {
  const runId = Date.now().toString(36);
  const name = `B3 demo ${runId}`;
  await signIn(page);

  await page.getByRole("navigation", { name: "Workspace" }).getByRole("link", {
    name: "Tools",
    exact: true,
  }).click();
  await page.waitForURL(`${WEB}/tools`);

  await page.getByLabel("Slug").fill(`b3-demo-${runId}`);
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Streamable HTTP endpoint").fill("http://demo-mcp:8100/mcp");
  await page.getByRole("button", { name: "Register server" }).click();
  await expect(page.getByRole("status")).toContainText("Server registered");

  const server = page.locator(".list-row").filter({ hasText: name });
  await expect(server).toBeVisible();
  await server.getByRole("button", { name: "Discover" }).click();
  await expect(page.getByRole("status")).toContainText("Discovered 1 tool");

  // Previous runs intentionally leave audit rows and registered servers behind.
  // Operate on one visible cached echo card without assuming this is a clean database.
  const tool = page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: "echo" }) })
    .last();
  await expect(tool).toContainText("Read-only");
  await tool.getByRole("button", { name: "Grant to me" }).click();
  await expect(page.getByRole("status")).toContainText("Granted echo");
  await tool.getByLabel("message").fill(`browser-${runId}`);
  await tool.getByRole("button", { name: "Propose call" }).click();
  await expect(page.getByRole("status")).toContainText("waiting below");

  const approval = page.getByRole("article").filter({ hasText: "Proposed call" });
  await expect(approval).toContainText(`browser-${runId}`);
  await approval.getByRole("button", { name: "Approve and run" }).click();
  await expect(page.getByRole("status")).toContainText("Invocation succeeded");
  await expect(page.getByRole("article").filter({ hasText: "Succeeded" }).first()).toContainText(
    `browser-${runId}`,
  );
});

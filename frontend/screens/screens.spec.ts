import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { installFixtures, NOW } from "./fixtures";

/**
 * The screenshot gallery: every main screen, at a phone and a desktop width,
 * in light and dark, rendered against `fixtures.ts`.
 *
 * Not a visual-regression test — nothing is compared here. It exists so a UI
 * change can be *seen* before it merges: run `npm run screens`, and the files
 * under `docs/screens/` change exactly where the UI did. A pull request then
 * carries its before and after as an ordinary image diff.
 *
 * Each case waits on something the screen genuinely renders when it is done
 * loading, never on a fixed delay, so a shot never catches a skeleton.
 */

const OUT_DIR = join(process.cwd(), "..", "docs", "screens");

test.beforeAll(() => {
  mkdirSync(OUT_DIR, { recursive: true });
});

test.beforeEach(async ({ page }) => {
  await page.clock.setFixedTime(NOW);
  await installFixtures(page);
});

async function shoot(page: Page, name: string, projectName: string): Promise<void> {
  // Let fonts finish and any entrance animation settle; reduced motion is on,
  // so this is a frame or two, not a timing guess.
  await page.evaluate(() => document.fonts.ready);
  // The Next dev-mode indicator is development chrome, not the product.
  await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
  await page.screenshot({ path: join(OUT_DIR, `${projectName}-${name}.jpg`), type: "jpeg", quality: 80 });
}

function isPhone(page: Page): boolean {
  return (page.viewportSize()?.width ?? 0) < 768;
}

test("overview", async ({ page }, info) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  await expect(page.getByText("Carry-over leave policy").first()).toBeVisible();
  await shoot(page, "overview", info.project.name);
});

test("chat", async ({ page }, info) => {
  await page.goto("/chat/s1");
  await expect(page.getByRole("button", { name: /Show source 3/ })).toBeVisible();
  await shoot(page, "chat", info.project.name);
});

test("chat with a citation open", async ({ page }, info) => {
  await page.goto("/chat/s1");
  await page.getByRole("button", { name: /Show source 1/ }).first().click();
  // On a phone the source opens under its paragraph; on a desktop, beside it
  // in the margin and in full in the inspector.
  const where = isPhone(page)
    ? page.getByRole("button", { name: "Open source 1 in the inspector", exact: true }).locator("xpath=ancestor::div[1]/..")
    : page.getByRole("complementary", { name: "Context inspector" });
  await expect(where.getByText("carry over a maximum of three").first()).toBeVisible();
  await shoot(page, "citation", info.project.name);
});

test("the context bundle behind an answer", async ({ page }, info) => {
  await page.goto("/chat/s1");
  await page.getByRole("button", { name: "Inspect answer" }).first().click();
  const inspector = isPhone(page)
    ? page.getByRole("dialog", { name: "Context inspector" })
    : page.getByRole("complementary", { name: "Context inspector" });
  await inspector.getByRole("button", { name: "Bundle" }).click();
  await expect(inspector.getByRole("heading", { name: "Hard token budget" })).toBeVisible();
  await expect(inspector.getByText("Employee Handbook 2025.pdf", { exact: false }).first()).toBeVisible();
  await shoot(page, "bundle", info.project.name);
});

test("a data answer and its SQL", async ({ page }, info) => {
  await page.goto("/chat/s2");
  await page.getByRole("textbox", { name: "Message", exact: true }).fill("Revenue by region for Q3");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByRole("table", { name: "Query results" })).toBeVisible();
  await page.getByRole("button", { name: "Inspect answer" }).click();
  const inspector = isPhone(page)
    ? page.getByRole("dialog", { name: "Context inspector" })
    : page.getByRole("complementary", { name: "Context inspector" });
  await inspector.getByRole("button", { name: "SQL" }).click();
  await expect(inspector.getByText("Allowed and run")).toBeVisible();
  await shoot(page, "sql", info.project.name);
});

test("navigation and account menu", async ({ page }, info) => {
  await page.goto("/chat/s1");
  if (isPhone(page)) {
    await page.getByRole("button", { name: "Show navigation", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Workspace" })).toBeVisible();
  }
  await page.getByRole("button", { name: /analyst@mnemos\.local/ }).click();
  await expect(page.getByRole("radiogroup", { name: "Appearance" })).toBeVisible();
  await shoot(page, "menu", info.project.name);
});

test("command palette", async ({ page }, info) => {
  test.skip(isPhone(page), "a keyboard feature; phones reach the same places from the navigation sheet");
  await page.goto("/chat/s1");
  await expect(page.getByRole("button", { name: /Show source 1/ })).toBeVisible();
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: "Go to or do" }).fill("go");
  await expect(page.getByRole("option").first()).toBeVisible();
  await shoot(page, "palette", info.project.name);
});

test("knowledge", async ({ page }, info) => {
  await page.goto("/knowledge");
  await expect(page.getByRole("table", { name: "Knowledge documents" })).toBeVisible();
  await shoot(page, "knowledge", info.project.name);
});

test("sources", async ({ page }, info) => {
  await page.goto("/sources");
  await page.getByRole("button", { name: /HR shared drive/ }).click();
  await expect(page.getByRole("table", { name: "Items at HR shared drive" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Ingestion activity" })).toBeVisible();
  await shoot(page, "sources", info.project.name);
});

test("memory", async ({ page }, info) => {
  await page.goto("/memory");
  const claims = page.getByRole("list", { name: "Memory claims" });
  await expect(claims.getByText("Jonas Weber, Head of Analytics").first()).toBeVisible();
  // The claim history is what this screen is for; the form above it is the
  // same shape on every visit.
  await claims.evaluate((element) => {
    // Clear the sticky toolbar rather than tucking the first claim under it.
    (element as HTMLElement).style.scrollMarginTop = "6rem";
    element.scrollIntoView({ block: "start" });
  });
  await shoot(page, "memory", info.project.name);
});

test("sign-in", async ({ page }, info) => {
  await page.goto("/signin");
  await expect(page.getByRole("button", { name: /continue with keycloak/i })).toBeVisible();
  await shoot(page, "signin", info.project.name);
});

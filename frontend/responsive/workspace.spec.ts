import { expect, test, type Page } from "@playwright/test";

const longName = "Employee_Handbook_" + "current_policy_".repeat(12) + ".txt";
const session = { id: "session-1", title: longName, folder_id: null, is_archived: false, created_at: "2026-09-10T00:00:00Z", updated_at: "2026-09-10T00:00:00Z", last_message_at: null };
const message = { id: "answer-1", session_id: session.id, role: "assistant", ordinal: 1, content: "The current policy allows five days [1]. " + longName, created_at: session.created_at, flow: "rag", router_rationale: "Answers from your documents.", bookmarked: false, feedback: null };
const citation = { id: "citation-1", message_id: message.id, marker: 1, document_id: "document-1", chunk_id: "chunk-1", quoted_text: ("Five days carry over. " + longName + " ").repeat(12), page_number: 1, start_char: 0, end_char: 100, score: 0.9 };
const document = { id: "document-1", title: longName, media_type: "text/plain", byte_size: 1200, status: "ready", chunk_count: 5, superseded_by: null, created_at: session.created_at };
const source = { id: "source-1", slug: "handbook", name: "Handbook source", kind: "local_fs", is_enabled: true, created_at: session.created_at };
const sql = { sql: "SELECT region, revenue FROM analytics.sales_order", verdict: "allowed", verdict_detail: null, attempt: 1, authorized_tables: ["analytics.sales_order"], denied_tables: [], executed: true, row_count: 2, truncated: false, duration_ms: 42, error_code: null, error_detail: null, columns: ["region", "revenue", "notes"], rows: [["West", 128400, longName], ["East", null, "true"]] };

async function fixtures(page: Page) {
  await page.routeWebSocket("**/ws/**", () => {});
  await page.route("http://localhost:8000/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = [];
    if (path.endsWith("/auth/token")) body = { access_token: "layout-fixture", token_type: "Bearer", expires_in: 900, org_slug: "mnemos" };
    else if (path.endsWith("/auth/me")) body = { user_id: "user-1", email: "analyst@mnemos.local", org_id: "org-1", org_slug: "mnemos", session_id: "auth-1", display_name: "Analyst", permissions: ["*:*"], tags: [] };
    else if (path === "/readyz") body = { status: "ready", checks: { postgres: "ok", redis: "ok", ollama: "ok", objectstore: "ok" } };
    else if (path.endsWith("/chat/sessions")) body = { sessions: [session] };
    else if (path.endsWith("/chat/sessions/session-1")) body = { session, messages: [message], citations: [citation] };
    else if (path.endsWith("/messages") && route.request().method() === "POST") {
      await route.fulfill({ contentType: "text/event-stream", body: `event: token\ndata: ${JSON.stringify({ text: "Revenue results." })}\n\nevent: done\ndata: ${JSON.stringify({ message: { ...message, id: "answer-2", content: "Revenue results.", flow: "nl2sql" }, nl2sql: sql })}\n\n` });
      return;
    }
    else if (path.endsWith("/chat/folders")) body = { folders: [] };
    else if (path.endsWith("/chat/bookmarks")) body = { bookmarks: [{ id: "bookmark-1", message_id: message.id, session_id: session.id, session_title: longName, message_content: message.content, note: longName }] };
    else if (path.endsWith("/knowledge/documents")) body = [document];
    else if (path.endsWith("/connectors")) body = [source, { ...source, id: "source-2", slug: "other", name: "Other source" }];
    else if (path.endsWith("/items")) body = [{ uri: longName, name: longName, content_type: "text/plain", size_bytes: 1200, modified_at: null }];
    else if (path.endsWith("/ingest")) body = { job_id: "job-1", status: "queued", uri: longName };
    else if (path.endsWith("/memories")) body = { claims: [], edges: [] };
    else if (path.endsWith("/audit/events")) body = { events: [{ id: "event-1", occurred_at: session.created_at, actor_id: "user-1", action: "tool.invoke", resource_kind: "tool", resource_id: "tool-1", outcome: "deny", reason: longName }] };
    else if (path.endsWith("/bundle")) { await route.fulfill({ status: 404, json: {} }); return; }
    await route.fulfill({ json: body });
  });
}

async function fits(page: Page) {
  const overflowing = await page.locator("body, main, [role=dialog], .workspace-shell, .workspace-toolbar, .table-region").evaluateAll((elements) => elements.filter((el) => {
    const box = el.getBoundingClientRect();
    return box.width > 0 && el.scrollWidth > el.clientWidth + 1;
  }).map((el) => `${el.tagName}.${el.className}: ${el.scrollWidth} > ${el.clientWidth}`));
  expect(overflowing).toEqual([]);
}

async function navigate(page: Page, label: string) {
  const mobile = (page.viewportSize()?.width ?? 0) < 768;
  if (mobile) await page.getByRole("button", { name: "Show navigation", exact: true }).click();
  const nav = mobile ? page.getByRole("dialog", { name: "Workspace", exact: true }) : page.getByRole("navigation", { name: "Workspace", exact: true });
  await nav.getByRole("link", { name: label, exact: true }).click();
  if (mobile) await expect(page.getByRole("dialog")).toHaveCount(0);
}

test.beforeEach(async ({ page }) => { await fixtures(page); });

test("all existing screens fit and keep navigation usable", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  for (const label of ["Knowledge", "Sources", "Memory", "Tools", "Bookmarks", "Audit log", "Overview"]) {
    await navigate(page, label);
    await expect(page.getByRole("heading", { name: label, exact: true })).toBeVisible();
    if (label === "Knowledge") {
      const table = page.getByRole("table", { name: "Knowledge documents" });
      await expect(table).toBeVisible();
      await table.getByRole("button", { name: `Delete ${longName}`, exact: true }).click();
      await expect(page.getByRole("dialog")).toBeVisible();
      await fits(page);
      await page.getByRole("button", { name: "Cancel", exact: true }).click();
    }
    if (label === "Audit log") await expect(page.getByRole("table", { name: "Audit events" })).toBeVisible();
    await fits(page);
    const inputs = await page.locator("main input:visible, main select:visible, main textarea:visible").evaluateAll((els) => els.filter((el) => (el as HTMLInputElement).type !== "checkbox").map((el) => parseFloat(getComputedStyle(el).fontSize)));
    expect(inputs.every((size) => size >= 16)).toBe(true);
  }
  expect(errors).toEqual([]);
});

test("source rows select, filter, reset on source change and queue from a touch action", async ({ page }) => {
  await page.goto("/sources");
  await page.getByRole("button", { name: /Handbook source/ }).click();
  await page.getByRole("checkbox", { name: `Select ${longName}`, exact: true }).check();
  await page.getByRole("textbox", { name: "Search source items" }).fill("no match");
  await expect(page.getByRole("button", { name: "Ingest 1", exact: true })).toBeEnabled();
  await page.getByRole("textbox", { name: "Search source items" }).fill("");
  await page.getByRole("button", { name: /Other source/ }).click();
  await expect(page.getByRole("checkbox", { name: `Select ${longName}`, exact: true })).not.toBeChecked();
  await page.getByRole("checkbox", { name: "Select all visible items" }).check();
  const request = page.waitForRequest((r) => r.url().endsWith("/other/ingest") && r.method() === "POST");
  await page.getByRole("button", { name: "Ingest 1", exact: true }).click();
  expect((await request).postDataJSON()).toEqual({ uri: longName });
  await expect(page.getByRole("list", { name: "Ingestion activity" })).toContainText("Queued");
  await fits(page);
});

test("chat keeps the composer reachable and opens readable evidence and SQL", async ({ page }) => {
  await page.goto("/chat/session-1");
  const marker = page.getByRole("button", { name: /Show source 1/ });
  await expect(page.getByRole("textbox", { name: "Message", exact: true })).toBeInViewport();
  await marker.click();
  const inline = (page.viewportSize()?.width ?? 0) >= 1280;
  const inspector = inline ? page.getByRole("complementary", { name: "Context inspector" }) : page.getByRole("dialog", { name: "Context inspector" });
  await expect(inspector.locator("blockquote")).toContainText("Five days carry over");
  await fits(page);
  if (!inline) {
    await inspector.getByRole("button", { name: "Close context inspector" }).click();
    await expect(marker).toBeFocused();
  }
  await page.setViewportSize({ width: page.viewportSize()!.width, height: 400 });
  const composer = page.getByRole("textbox", { name: "Message", exact: true });
  await composer.fill("Revenue by region");
  await expect(composer).toBeInViewport();
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByRole("table", { name: "Query results" })).toBeVisible();
  await page.getByRole("table", { name: "Query results" }).scrollIntoViewIfNeeded();
  await fits(page);
  await expect(composer).toBeInViewport();
  await expect(page.getByRole("table", { name: "Query results" }).getByRole("cell", { name: /128400/ })).toBeVisible();
});

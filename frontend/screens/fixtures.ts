import type { Page, Route } from "@playwright/test";

/**
 * One deterministic workspace, answered at the API boundary.
 *
 * The screenshot harness renders the real frontend against these responses
 * rather than against the Compose stack, so a picture changes only when the
 * UI does — never because a model answered differently or a job finished at
 * another moment. The data is chosen to exercise what each screen is *for*:
 * an answer with citations on two paragraphs, a superseded document revision,
 * a superseded memory claim, a running and a failed ingestion job, and a
 * persisted context bundle with admitted and excluded items.
 *
 * Every timestamp is relative to `NOW`, which the spec pins the browser clock
 * to, so "2h ago" reads the same on every run.
 */
export const NOW = "2026-10-22T10:00:00Z";

const at = (minutesAgo: number): string =>
  new Date(Date.parse(NOW) - minutesAgo * 60_000).toISOString();

const HOUR = 60;
const DAY = 24 * HOUR;

const folders = [{ id: "f1", name: "HR policy", created_at: at(9 * DAY), updated_at: at(9 * DAY) }];

const sessions = [
  { id: "s1", title: "Carry-over leave policy", folder_id: "f1", is_archived: false, created_at: at(2 * HOUR + 20), updated_at: at(2 * HOUR), last_message_at: at(2 * HOUR) },
  { id: "s2", title: "Q3 revenue by region", folder_id: null, is_archived: false, created_at: at(26 * HOUR), updated_at: at(26 * HOUR), last_message_at: at(26 * HOUR) },
  { id: "s3", title: "Onboarding checklist for new analysts joining the Bengaluru office", folder_id: null, is_archived: false, created_at: at(5 * DAY), updated_at: at(5 * DAY), last_message_at: at(5 * DAY) },
  { id: "s4", title: "Expense limits for client travel", folder_id: null, is_archived: false, created_at: at(12 * DAY), updated_at: at(12 * DAY), last_message_at: at(12 * DAY) },
];

const message = <T extends Record<string, unknown>>(fields: T) => ({
  flow: null,
  router_rationale: null,
  bundle_id: null,
  prompt_tokens: 0,
  completion_tokens: 0,
  latency_ms: null,
  model: null,
  finish_reason: null,
  bookmarked: false,
  feedback: null,
  ...fields,
});

const messages = [
  message({ id: "u1", role: "user", ordinal: 0, created_at: at(2 * HOUR + 4), content: "How many leave days can I carry over into next year?" }),
  message({
    id: "a1",
    role: "assistant",
    ordinal: 1,
    created_at: at(2 * HOUR + 3),
    flow: "rag",
    router_rationale: "Asks about documents or cited knowledge.",
    bundle_id: "b1",
    content:
      "Under the 2026 handbook you can carry over up to three unused days into the next calendar year [1]. The 2025 handbook allowed five; that revision is superseded, so it was left out of this answer.\n\nCarried-over days lapse on 31 March unless your line manager approves an exception in writing [2].",
  }),
  message({ id: "u2", role: "user", ordinal: 2, created_at: at(2 * HOUR + 1), content: "Who approves the exception if my manager is on leave?" }),
  message({
    id: "a2",
    role: "assistant",
    ordinal: 3,
    created_at: at(2 * HOUR),
    flow: "rag",
    router_rationale: "Asks about documents or cited knowledge.",
    bookmarked: true,
    feedback: "up",
    content:
      "The approval passes to the next manager in your reporting line, or to HR operations when that person is also away [3].",
  }),
];

const citations = [
  { id: "c1", message_id: "a1", marker: 1, document_id: "d1", chunk_id: "k1", quoted_text: "Employees may carry over a maximum of three (3) unused annual leave days into the following calendar year.", page_number: 4, start_char: 1180, end_char: 1290, score: 0.91 },
  { id: "c2", message_id: "a1", marker: 2, document_id: "d1", chunk_id: "k2", quoted_text: "Carried-over days not used by 31 March lapse, except where an exception is approved in writing by the line manager.", page_number: 4, start_char: 1291, end_char: 1406, score: 0.84 },
  { id: "c3", message_id: "a2", marker: 3, document_id: "d1", chunk_id: "k3", quoted_text: "Where the line manager is absent, approval passes to the next manager in the reporting line or, failing that, to HR Operations.", page_number: 5, start_char: 210, end_char: 336, score: 0.79 },
];

const documents = [
  { id: "d1", title: "Employee Handbook 2026.pdf", media_type: "application/pdf", byte_size: 482113, status: "ready", chunk_count: 64, superseded_by: null, created_at: at(3 * DAY) },
  { id: "d0", title: "Employee Handbook 2025.pdf", media_type: "application/pdf", byte_size: 455020, status: "ready", chunk_count: 61, superseded_by: "d1", created_at: at(290 * DAY) },
  { id: "d2", title: "Travel and expenses policy.md", media_type: "text/markdown", byte_size: 12000, status: "ready", chunk_count: 9, superseded_by: null, created_at: at(6 * DAY) },
  { id: "d3", title: "Security standards v2.docx", media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", byte_size: 90000, status: "processing", chunk_count: 0, superseded_by: null, created_at: at(40) },
];

const sources = [
  { id: "src1", slug: "hr-drive", name: "HR shared drive", kind: "local_fs", is_enabled: true, created_at: at(9 * DAY) },
  { id: "src2", slug: "policy-bucket", name: "Policy bucket", kind: "minio", is_enabled: true, created_at: at(20 * DAY) },
];

const items = [
  { uri: "file:///fixtures/hr/Employee Handbook 2026.pdf", name: "Employee Handbook 2026.pdf", content_type: "application/pdf", size_bytes: 482113, modified_at: at(4 * DAY) },
  { uri: "file:///fixtures/hr/Security standards v2.docx", name: "Security standards v2.docx", content_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document", size_bytes: 90000, modified_at: at(2 * DAY) },
  { uri: "file:///fixtures/hr/Expenses FAQ.html", name: "Expenses FAQ.html", content_type: "text/html", size_bytes: 18400, modified_at: at(8 * DAY) },
];

const jobEvent = (id: string, from: string | null, to: string, minutesAgo: number, detail: string | null = null) => ({
  id,
  from_status: from,
  to_status: to,
  owner_id: from === null ? null : "worker-1",
  detail,
  occurred_at: at(minutesAgo),
});

const job = <T extends Record<string, unknown>>(fields: T) => ({
  kind: "connector.ingest",
  document_id: null,
  attempts: 1,
  max_attempts: 3,
  done_units: 4,
  total_units: 4,
  owner_id: "worker-1",
  heartbeat_at: null,
  lease_expires_at: null,
  started_at: null,
  finished_at: null,
  error_code: null,
  error_detail: null,
  events: [],
  ...fields,
});

const jobs = [
  job({ id: "j2", status: "running", payload: { source_slug: "hr-drive", item_name: "Security standards v2.docx" }, done_units: 2, created_at: at(41), updated_at: at(1), started_at: at(40), heartbeat_at: at(1), lease_expires_at: at(-1), events: [jobEvent("e21", null, "queued", 41), jobEvent("e22", "queued", "running", 40)] }),
  job({ id: "j3", status: "failed", payload: { source_slug: "hr-drive", item_name: "Expenses FAQ.html" }, attempts: 3, done_units: 1, created_at: at(5 * HOUR), updated_at: at(4 * HOUR), finished_at: at(4 * HOUR), error_code: "extract_failed", error_detail: "the HTML had no readable body text", events: [jobEvent("e31", null, "queued", 5 * HOUR), jobEvent("e32", "queued", "running", 5 * HOUR), jobEvent("e33", "running", "failed", 4 * HOUR, "the HTML had no readable body text")] }),
  job({ id: "j1", status: "succeeded", payload: { source_slug: "hr-drive", item_name: "Employee Handbook 2026.pdf" }, document_id: "d1", created_at: at(3 * DAY), updated_at: at(3 * DAY - 2), finished_at: at(3 * DAY - 2), events: [jobEvent("e11", null, "queued", 3 * DAY), jobEvent("e12", "queued", "running", 3 * DAY - 1), jobEvent("e13", "running", "succeeded", 3 * DAY - 2)] }),
];

const subject = { id: "subj1", kind: "person", external_ref: "employee:priya", display_name: "Priya Raman" };
const claim = <T extends Record<string, unknown>>(fields: T) => ({
  subject,
  kind: "fact",
  scope: {},
  retracted_at: null,
  confidence: 1,
  trust_tier: 40,
  source_kind: "user",
  source_ref: null,
  ...fields,
});

const memory = {
  claims: [
    claim({ id: "m2", predicate: "reports_to", object_text: "Jonas Weber, Head of Analytics", status: "active", valid_from: "2026-07-01T00:00:00Z", valid_to: "9999-12-31T23:59:59Z", recorded_at: at(30 * DAY) }),
    claim({ id: "m1", predicate: "reports_to", object_text: "Elena Petrova, Analytics Lead", status: "superseded", valid_from: "2025-03-01T00:00:00Z", valid_to: "2026-07-01T00:00:00Z", recorded_at: at(200 * DAY) }),
    claim({ id: "m3", predicate: "prefers_format", object_text: "Short answers with the source page", kind: "preference", status: "active", valid_from: at(10 * DAY), valid_to: "9999-12-31T23:59:59Z", recorded_at: at(10 * DAY), confidence: 0.8 }),
  ],
  edges: [{ id: "edge1", source_id: "m2", target_id: "m1", kind: "supersedes", rationale: "new overlapping fact superseded the prior live belief", created_at: at(30 * DAY) }],
};

const bundle = {
  id: "b1",
  digest: "9f2c4e1ab07d5c3e88a1",
  flow: "rag",
  token_budget: 800,
  tokens_consumed: 412,
  compiled_prompt: "[SYSTEM]\nAnswer only from the admitted context. Cite passages by marker.\n\n[CONTEXT]\n[1] Employees may carry over a maximum of three (3) unused annual leave days…\n[2] Carried-over days not used by 31 March lapse…\n\n[QUESTION]\nHow many leave days can I carry over into next year?",
  budget_report: {},
  explain: { refine: { conflicts_demoted: 1, conflicts: [{ candidate: "Employee Handbook 2025.pdf §4.2", preferred_source: "Employee Handbook 2026.pdf §4.2" }] } },
  admitted: [
    { id: "bi1", position: 0, section: "evidence", operator: "hybrid", text: citations[0]!.quoted_text, tokens: 31, raw_score: 0.91, rrf_score: 0.032, utility: 0.912, density: 0.0294, trust_tier: 40, source_kind: "document", source_ref: "d1#k1", document_title: "Employee Handbook 2026.pdf", acl_rule: "tag:hr-all", memory_id: null },
    { id: "bi2", position: 1, section: "evidence", operator: "hybrid", text: citations[1]!.quoted_text, tokens: 29, raw_score: 0.84, rrf_score: 0.031, utility: 0.842, density: 0.029, trust_tier: 40, source_kind: "document", source_ref: "d1#k2", document_title: "Employee Handbook 2026.pdf", acl_rule: "tag:hr-all", memory_id: null },
    { id: "bi3", position: 2, section: "memory", operator: "memory", text: "Priya Raman prefers short answers with the source page.", tokens: 14, raw_score: 0.6, rrf_score: 0.02, utility: 0.55, density: 0.0393, trust_tier: 40, source_kind: "memory", source_ref: "memory:m3", document_title: null, acl_rule: "owner", memory_id: "m3" },
  ],
  rejections: [
    { key: "d0#k1", section: "evidence", source_kind: "document", source_ref: "Employee Handbook 2025.pdf §4.2", reason: "superseded_revision", tokens: 30, utility: 0.93, detail: "Superseded by Employee Handbook 2026.pdf." },
    { key: "d2#k4", section: "evidence", source_kind: "document", source_ref: "Travel and expenses policy.md §2", reason: "below_utility_floor", tokens: 44, utility: 0.08, detail: null },
  ],
  lineage: [{ source_id: "d1", target_id: "d0", kind: "supersedes", rationale: "2026 revision of the handbook" }],
  created_at: at(2 * HOUR + 3),
};

const auditEvents = [
  { id: "ev1", occurred_at: at(35), actor_id: "user-1-analyst", action: "tool.invoke", resource_kind: "tool", resource_id: "web-search-01", outcome: "deny", reason: "tool:invoke not granted" },
  { id: "ev2", occurred_at: at(2 * HOUR), actor_id: "user-1-analyst", action: "auth.sign_in", resource_kind: "session", resource_id: "auth-1", outcome: "allow", reason: null },
  { id: "ev3", occurred_at: at(30 * DAY), actor_id: "user-1-analyst", action: "memory.supersede", resource_kind: "memory", resource_id: "m2", outcome: "allow", reason: null },
];

const identity = { user_id: "user-1", email: "analyst@mnemos.local", org_id: "org-1", org_slug: "mnemos", session_id: "auth-1", display_name: "Analyst", permissions: ["*:*"], tags: ["hr-all"] };

function answer(path: string): unknown {
  if (path.endsWith("/auth/token")) return { access_token: "screens-fixture", token_type: "Bearer", expires_in: 900, org_slug: "mnemos" };
  if (path.endsWith("/auth/me")) return identity;
  if (path === "/readyz") return { status: "ready", checks: { postgres: "ok", redis: "ok", ollama: "ok", objectstore: "ok" } };
  if (path.endsWith("/chat/sessions")) return { sessions, next_cursor: null };
  const session = /\/chat\/sessions\/([^/]+)$/.exec(path);
  if (session) {
    const found = sessions.find((item) => item.id === session[1]) ?? sessions[0]!;
    return found.id === "s1" ? { session: found, messages, citations } : { session: found, messages: [], citations: [] };
  }
  if (path.endsWith("/chat/folders")) return { folders };
  if (path.endsWith("/chat/bookmarks")) return { bookmarks: [{ id: "bm1", message_id: "a2", session_id: "s1", session_title: "Carry-over leave policy", message_content: messages[3]!.content, note: "For the team FAQ" }] };
  if (path.endsWith("/knowledge/documents")) return documents;
  if (path.endsWith("/connectors/jobs")) return jobs;
  if (path.endsWith("/connectors")) return sources;
  if (path.endsWith("/items")) return items;
  if (path.endsWith("/memories")) return memory;
  if (path.endsWith("/audit/events")) return { events: auditEvents };
  if (path.endsWith("/tools/servers") || path.endsWith("/tools") || path.endsWith("/tools/invocations")) return [];
  return undefined;
}

const SQL_ANSWER_TEXT = "West led Q3 with 128,400 in revenue, ahead of East (97,210) and North (64,020).";

/** The NL2SQL answer a question sent on screen receives, as the live `done` frame. */
const sqlAnswer = {
  message: message({ id: "a-sql", role: "assistant", ordinal: 1, created_at: NOW, flow: "nl2sql", router_rationale: "Asks for a business metric or data breakdown.", content: SQL_ANSWER_TEXT }),
  nl2sql: {
    sql: "SELECT region, SUM(revenue) AS revenue\nFROM analytics.sales_order\nWHERE quarter = '2026-Q3'\nGROUP BY region\nORDER BY revenue DESC",
    verdict: "allowed", verdict_detail: null, attempt: 1, authorized_tables: ["analytics.sales_order"], denied_tables: [],
    executed: true, row_count: 3, truncated: false, duration_ms: 42, error_code: null, error_detail: null,
    columns: ["region", "revenue"], rows: [["West", 128400], ["East", 97210], ["North", 64020]],
  },
};

const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

export async function installFixtures(page: Page): Promise<void> {
  await page.routeWebSocket("**/ws/**", () => {});
  await page.route("http://localhost:8000/**", async (route: Route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/messages") && route.request().method() === "POST") {
      await route.fulfill({
        contentType: "text/event-stream",
        body:
          sse("route", { flow: "nl2sql", reason: "Asks for a business metric or data breakdown." }) +
          sse("token", { text: SQL_ANSWER_TEXT }) +
          sse("done", sqlAnswer),
      });
      return;
    }
    if (/\/context\/messages\/[^/]+\/bundle$/.test(path)) {
      if (path.includes("/a1/")) await route.fulfill({ json: bundle });
      else await route.fulfill({ status: 404, json: { detail: "no bundle" } });
      return;
    }
    const body = answer(path);
    if (body === undefined) await route.fulfill({ status: 404, json: { detail: "not in the screenshot fixtures" } });
    else await route.fulfill({ json: body });
  });
}

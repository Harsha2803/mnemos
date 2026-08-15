/**
 * The streaming half of the chat surface: `POST .../messages`, read as
 * `text/event-stream`.
 *
 * **Deliberately not `EventSource`.** `EventSource` cannot set an
 * `Authorization` header, and the only other way to authenticate it is a token
 * in the URL — which is a credential in browser history, in every proxy log,
 * and in the next request's `Referer`, exactly what `A0`'s callback redirect
 * was built to avoid (TRACKER §4 item 34). `fetch` with a `ReadableStream`
 * reader can set headers, so that is what this uses. If a future change needs
 * a browser-native EventSource, it needs a different authentication story
 * first — not a token pasted into the URL to make it fit.
 *
 * **Does not go through `authenticatedFetch`** (`lib/api/client.ts`): that
 * helper clones the request for a retry, and cloning a `Response` whose body
 * is being read as a live stream is not the same operation as cloning one
 * before it has been touched. The one-refresh-on-401 behaviour is
 * reimplemented here instead, narrowly, for the one request that needs it.
 */

import { API_BASE_URL } from "@/lib/api/client";
import { refreshAccessToken } from "@/lib/auth/refresh";
import { getAccessToken } from "@/lib/auth/session";
import type { components } from "@/lib/api/schema";

export type ChatMessage = components["schemas"]["ChatMessageResponse"];

/**
 * The read-only AST guard's five outcomes (`SqlVerdict` on the backend,
 * `core/types.py`). Only `"allowed"` ever executes — every other value means
 * the statement was refused before it touched `mnemos_analytics`.
 */
export type Nl2SqlVerdict =
  | "allowed"
  | "rejected_write"
  | "rejected_unauthorized_table"
  | "rejected_unparseable"
  | "rejected_too_complex";

/** One result-grid cell, exactly as JSON can carry a Postgres value. */
export type SqlCellValue = string | number | boolean | null;

/**
 * The `nl2sql` key on the `done` SSE frame (see `AssistantDone.extra` on the
 * backend). Not part of the generated OpenAPI schema — it rides the
 * hand-parsed SSE payload, not a typed response model — so it is hand-typed
 * here, matching `flows/nl2sql/application/service.py::Nl2SqlFlow._finish`'s
 * `extra` dict field for field.
 */
export type Nl2SqlResult = {
  sql: string;
  verdict: Nl2SqlVerdict;
  verdict_detail: string | null;
  attempt: number;
  authorized_tables: string[];
  denied_tables: string[];
  executed: boolean;
  row_count: number | null;
  truncated: boolean;
  duration_ms: number | null;
  error_code: string | null;
  error_detail: string | null;
  columns: string[];
  rows: SqlCellValue[][];
};

export type ChatStreamHandlers = {
  onToken: (text: string) => void;
  /** `nl2sql` is present only when the answer came from the NL2SQL flow. */
  onDone: (message: ChatMessage, nl2sql?: Nl2SqlResult) => void;
  onError: (message: string) => void;
};

export type ChatStreamOptions = {
  /**
   * Answer from the knowledge base rather than the model alone. Manual for
   * now — `A4`'s classifier replaces this with real routing, and the backend
   * says the same thing in `SendMessageRequest`.
   */
  useDocuments?: boolean;
  /**
   * Answer by generating and running SQL against the registered datasource.
   * Same provisionality as `useDocuments`, and mutually exclusive with it —
   * the backend 422s if both are `true`.
   */
  useDatasource?: boolean;
};

/**
 * Streams one reply. Resolves once the stream ends, however it ended —
 * `onDone`/`onError` is how the caller learns which.
 */
export async function streamChatReply(
  sessionId: string,
  content: string,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
  options: ChatStreamOptions = {},
): Promise<void> {
  const url = `${API_BASE_URL}/api/v1/chat/sessions/${sessionId}/messages`;
  const body = JSON.stringify({
    content,
    use_documents: options.useDocuments ?? false,
    use_datasource: options.useDatasource ?? false,
  });

  let response = await send(url, body, getAccessToken(), signal);
  if (response.status === 401) {
    const token = await refreshAccessToken();
    if (token === null) {
      handlers.onError("you are signed out");
      return;
    }
    response = await send(url, body, token, signal);
  }

  if (!response.ok || response.body === null) {
    handlers.onError("could not reach the assistant");
    return;
  }

  await readFrames(response.body, handlers);
}

function send(
  url: string,
  body: string,
  token: string | null,
  signal: AbortSignal | undefined,
): Promise<Response> {
  const headers: HeadersInit = { "content-type": "application/json" };
  if (token !== null) headers.authorization = `Bearer ${token}`;
  return globalThis.fetch(url, { method: "POST", headers, body, signal });
}

async function readFrames(
  body: ReadableStream<Uint8Array>,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      dispatch(buffer.slice(0, boundary), handlers);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function dispatch(frame: string, handlers: ChatStreamHandlers): void {
  const lines = frame.split("\n");
  const eventLine = lines.find((line) => line.startsWith("event: "));
  const dataLine = lines.find((line) => line.startsWith("data: "));
  if (eventLine === undefined || dataLine === undefined) return;

  const name = eventLine.slice("event: ".length);
  const payload: unknown = JSON.parse(dataLine.slice("data: ".length));
  if (typeof payload !== "object" || payload === null) return;
  const record = payload as Record<string, unknown>;

  if (name === "token" && typeof record.text === "string") {
    handlers.onToken(record.text);
  } else if (name === "done" && isChatMessage(record.message)) {
    handlers.onDone(record.message, isNl2SqlResult(record.nl2sql) ? record.nl2sql : undefined);
  } else if (name === "error" && typeof record.message === "string") {
    handlers.onError(record.message);
  }
}

function isChatMessage(value: unknown): value is ChatMessage {
  return typeof value === "object" && value !== null && "id" in value && "role" in value;
}

function isNl2SqlResult(value: unknown): value is Nl2SqlResult {
  return typeof value === "object" && value !== null && "sql" in value && "verdict" in value;
}

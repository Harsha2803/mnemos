/**
 * The knowledge library's calls: list, upload, delete.
 *
 * `upload` does **not** go through the generated client. `openapi-fetch`
 * serialises a `multipart/form-data` body from a plain object, and the API
 * takes an actual file part — so this one call builds its own `FormData` and
 * goes through `authenticatedFetch` directly, which still attaches the bearer
 * and still refreshes once on a 401. Everything else is generated-client
 * typed, so a renamed field stays a compile error.
 */

import { api, API_BASE_URL } from "@/lib/api/client";
import { refreshAccessToken } from "@/lib/auth/refresh";
import { getAccessToken } from "@/lib/auth/session";
import type { components } from "@/lib/api/schema";

export type KnowledgeDocument = components["schemas"]["DocumentResponse"];
export type Citation = components["schemas"]["CitationResponse"];

/**
 * Here rather than in the page module: Next.js allows only a fixed set of
 * exports from a `page.tsx` (`default`, `metadata`, a few route options), and
 * anything else is a build error rather than a warning.
 */
export const KNOWLEDGE_QUERY_KEY = ["knowledge", "documents"] as const;

export async function fetchDocuments(signal?: AbortSignal): Promise<KnowledgeDocument[]> {
  const { data, error } = await api.GET("/api/v1/knowledge/documents", { signal });
  if (error !== undefined) throw new Error("could not load the knowledge library");
  return data;
}

export async function deleteDocument(documentId: string): Promise<void> {
  const { error } = await api.DELETE("/api/v1/knowledge/documents/{document_id}", {
    params: { path: { document_id: documentId } },
  });
  if (error !== undefined) throw new Error("could not delete this document");
}

/**
 * Upload one file. Throws with the API's own message when it refuses —
 * "unsupported media type" and "too large" are both answers the user can act
 * on, and `ValidationError` is the one error whose details cross the API
 * boundary deliberately (`core/errors.py`).
 */
export async function uploadDocument(file: File): Promise<KnowledgeDocument> {
  const body = new FormData();
  body.append("file", file);

  let response = await send(body, getAccessToken());
  if (response.status === 401) {
    const token = await refreshAccessToken();
    if (token === null) throw new Error("you are signed out");
    response = await send(body, token);
  }

  if (!response.ok) throw new Error(await readError(response));
  return (await response.json()) as KnowledgeDocument;
}

function send(body: FormData, token: string | null): Promise<Response> {
  const headers = new Headers();
  if (token !== null) headers.set("Authorization", `Bearer ${token}`);
  // Deliberately no `content-type`: the browser sets it, and it has to
  // include the multipart boundary it generated. Setting it by hand produces
  // a body the server cannot parse.
  return globalThis.fetch(`${API_BASE_URL}/api/v1/knowledge/documents`, {
    method: "POST",
    headers,
    body,
  });
}

async function readError(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json();
    if (typeof payload === "object" && payload !== null && "error" in payload) {
      const error = (payload as { error?: { message?: unknown } }).error;
      if (typeof error?.message === "string") return error.message;
    }
  } catch {
    // Fall through to the generic message: a body we cannot parse is not a
    // reason to show the user a stack trace.
  }
  return "could not upload this document";
}

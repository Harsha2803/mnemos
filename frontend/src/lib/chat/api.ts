/**
 * The non-streaming half of the chat surface: session CRUD through the
 * generated client. `stream.ts` is the other half — the one call that cannot
 * go through `openapi-fetch`'s `fetch` wrapper.
 */

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ChatSession = components["schemas"]["ChatSessionResponse"];
export type ChatSessionDetail = components["schemas"]["ChatSessionDetailResponse"];
export type ChatSessionList = components["schemas"]["ChatSessionListResponse"];

export async function fetchSessions(signal?: AbortSignal): Promise<ChatSessionList> {
  const { data, error } = await api.GET("/api/v1/chat/sessions", { signal });
  if (error !== undefined) throw new Error("could not load conversations");
  return data;
}

export async function fetchSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<ChatSessionDetail> {
  const { data, error } = await api.GET("/api/v1/chat/sessions/{session_id}", {
    params: { path: { session_id: sessionId } },
    signal,
  });
  if (error !== undefined) throw new Error("could not load this conversation");
  return data;
}

export async function createSession(title?: string): Promise<ChatSession> {
  const { data, error } = await api.POST("/api/v1/chat/sessions", {
    body: { title: title ?? null },
  });
  if (error !== undefined) throw new Error("could not start a new conversation");
  return data;
}

export async function renameSession(sessionId: string, title: string): Promise<ChatSession> {
  const { data, error } = await api.PATCH("/api/v1/chat/sessions/{session_id}", {
    params: { path: { session_id: sessionId } },
    body: { title },
  });
  if (error !== undefined) throw new Error("could not rename this conversation");
  return data;
}

export async function deleteSession(sessionId: string): Promise<void> {
  const { error } = await api.DELETE("/api/v1/chat/sessions/{session_id}", {
    params: { path: { session_id: sessionId } },
  });
  if (error !== undefined) throw new Error("could not delete this conversation");
}

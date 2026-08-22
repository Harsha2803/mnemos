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
export type Folder = components["schemas"]["FolderResponse"];
export type FolderList = components["schemas"]["FolderListResponse"];
export type Bookmark = components["schemas"]["BookmarkResponse"];
export type BookmarkedMessage = components["schemas"]["BookmarkedMessageResponse"];
export type BookmarkList = components["schemas"]["BookmarkListResponse"];
export type Feedback = components["schemas"]["FeedbackResponse"];
export type FeedbackRating = Feedback["rating"];

/**
 * `query` switches the list from recency-ordered to search-ranked (title
 * matches first, then full-text content matches) — same endpoint, same
 * response shape, an optional `snippet` on rows that matched by content
 * rather than title (TRACKER §5 deliverable 4).
 */
export async function fetchSessions(
  signal?: AbortSignal,
  query?: string,
): Promise<ChatSessionList> {
  const { data, error } = await api.GET("/api/v1/chat/sessions", {
    signal,
    params: { query: query ? { q: query } : {} },
  });
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

/**
 * `folder_id` is tri-state on the wire: omit it to leave the session's folder
 * untouched (the default here — most callers only rename), pass a folder id
 * to file it, or pass `null` to un-file it. `JSON.stringify` drops an
 * `undefined` property entirely, which is what makes "omitted" distinguishable
 * from "explicitly null" once it reaches the backend's `model_fields_set`
 * check (TRACKER §5 deliverable 1).
 */
export async function renameSession(
  sessionId: string,
  title: string,
  folderId?: string | null,
): Promise<ChatSession> {
  const { data, error } = await api.PATCH("/api/v1/chat/sessions/{session_id}", {
    params: { path: { session_id: sessionId } },
    body: folderId === undefined ? { title } : { title, folder_id: folderId },
  });
  if (error !== undefined) throw new Error("could not rename this conversation");
  return data;
}

export async function moveSessionToFolder(
  sessionId: string,
  folderId: string | null,
): Promise<ChatSession> {
  const { data, error } = await api.PATCH("/api/v1/chat/sessions/{session_id}", {
    params: { path: { session_id: sessionId } },
    body: { folder_id: folderId },
  });
  if (error !== undefined) throw new Error("could not move this conversation");
  return data;
}

export async function deleteSession(sessionId: string): Promise<void> {
  const { error } = await api.DELETE("/api/v1/chat/sessions/{session_id}", {
    params: { path: { session_id: sessionId } },
  });
  if (error !== undefined) throw new Error("could not delete this conversation");
}

export const CHAT_FOLDERS_QUERY_KEY = ["chat", "folders"] as const;

export async function fetchFolders(signal?: AbortSignal): Promise<FolderList> {
  const { data, error } = await api.GET("/api/v1/chat/folders", { signal });
  if (error !== undefined) throw new Error("could not load folders");
  return data;
}

export async function createFolder(name: string): Promise<Folder> {
  const { data, error } = await api.POST("/api/v1/chat/folders", { body: { name } });
  if (error !== undefined) throw new Error("could not create this folder");
  return data;
}

export async function renameFolder(folderId: string, name: string): Promise<Folder> {
  const { data, error } = await api.PATCH("/api/v1/chat/folders/{folder_id}", {
    params: { path: { folder_id: folderId } },
    body: { name },
  });
  if (error !== undefined) throw new Error("could not rename this folder");
  return data;
}

export async function reorderFolder(folderId: string, position: number): Promise<Folder> {
  const { data, error } = await api.PATCH("/api/v1/chat/folders/{folder_id}", {
    params: { path: { folder_id: folderId } },
    body: { position },
  });
  if (error !== undefined) throw new Error("could not reorder this folder");
  return data;
}

export async function deleteFolder(folderId: string): Promise<void> {
  const { error } = await api.DELETE("/api/v1/chat/folders/{folder_id}", {
    params: { path: { folder_id: folderId } },
  });
  if (error !== undefined) throw new Error("could not delete this folder");
}

export const CHAT_BOOKMARKS_QUERY_KEY = ["chat", "bookmarks"] as const;

export async function upsertBookmark(messageId: string, note?: string): Promise<Bookmark> {
  const { data, error } = await api.PUT("/api/v1/chat/messages/{message_id}/bookmark", {
    params: { path: { message_id: messageId } },
    body: { note: note ?? null },
  });
  if (error !== undefined) throw new Error("could not bookmark this message");
  return data;
}

export async function removeBookmark(messageId: string): Promise<void> {
  const { error } = await api.DELETE("/api/v1/chat/messages/{message_id}/bookmark", {
    params: { path: { message_id: messageId } },
  });
  if (error !== undefined) throw new Error("could not remove this bookmark");
}

export async function fetchBookmarks(signal?: AbortSignal): Promise<BookmarkList> {
  const { data, error } = await api.GET("/api/v1/chat/bookmarks", { signal });
  if (error !== undefined) throw new Error("could not load bookmarks");
  return data;
}

export async function upsertFeedback(
  messageId: string,
  rating: FeedbackRating,
  comment?: string,
): Promise<Feedback> {
  const { data, error } = await api.PUT("/api/v1/chat/messages/{message_id}/feedback", {
    params: { path: { message_id: messageId } },
    body: { rating, comment: comment ?? null },
  });
  if (error !== undefined) throw new Error("could not save this rating");
  return data;
}

export async function removeFeedback(messageId: string): Promise<void> {
  const { error } = await api.DELETE("/api/v1/chat/messages/{message_id}/feedback", {
    params: { path: { message_id: messageId } },
  });
  if (error !== undefined) throw new Error("could not clear this rating");
}

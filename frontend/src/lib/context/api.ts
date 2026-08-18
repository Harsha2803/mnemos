import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ContextBundle = components["schemas"]["ContextBundleResponse"];

export function contextBundleQueryKey(messageId: string) {
  return ["context", "bundle", messageId] as const;
}

export async function fetchContextBundle(
  messageId: string,
  signal?: AbortSignal,
): Promise<ContextBundle | null> {
  const { data, error, response } = await api.GET(
    "/api/v1/context/messages/{message_id}/bundle",
    { params: { path: { message_id: messageId } }, signal },
  );
  if (response.status === 404) return null;
  if (error !== undefined || data === undefined) {
    throw new Error("could not load this context bundle");
  }
  return data;
}

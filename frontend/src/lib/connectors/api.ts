/**
 * The connectors library's calls: register a source, list sources, browse
 * one, enqueue an ingest. All generated-client typed — unlike
 * `lib/knowledge/api.ts`'s upload, none of these bodies are multipart, so
 * there is no hand-built `fetch` here.
 */

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ContentSource = components["schemas"]["SourceResponse"];
export type SourceItem = components["schemas"]["ItemResponse"];
export type RegisterSourceRequest = components["schemas"]["RegisterSourceRequest"];
export type IngestResponse = components["schemas"]["IngestResponse"];

export const SOURCES_QUERY_KEY = ["connectors", "sources"] as const;
export const itemsQueryKey = (slug: string) => ["connectors", "sources", slug, "items"] as const;

export async function fetchSources(signal?: AbortSignal): Promise<ContentSource[]> {
  const { data, error } = await api.GET("/api/v1/connectors", { signal });
  if (error !== undefined) throw new Error("could not load the registered sources");
  return data;
}

/**
 * Throws with the API's own message when registration is refused — a
 * `local_fs` root outside the operator-approved roots, a duplicate slug, an
 * `http` url that fails the SSRF deny-list — all of which are things the
 * person filling in the form can act on.
 */
export async function registerSource(body: RegisterSourceRequest): Promise<ContentSource> {
  const { data, error } = await api.POST("/api/v1/connectors", { body });
  if (error !== undefined) throw new Error(errorMessage(error, "could not register this source"));
  return data;
}

export async function fetchItems(slug: string, signal?: AbortSignal): Promise<SourceItem[]> {
  const { data, error } = await api.GET("/api/v1/connectors/{slug}/items", {
    params: { path: { slug } },
    signal,
  });
  if (error !== undefined) throw new Error(errorMessage(error, "could not browse this source"));
  return data;
}

export async function ingestItem(slug: string, uri: string): Promise<IngestResponse> {
  const { data, error } = await api.POST("/api/v1/connectors/{slug}/ingest", {
    params: { path: { slug } },
    body: { uri },
  });
  if (error !== undefined) throw new Error(errorMessage(error, "could not queue this item"));
  return data;
}

function errorMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "error" in error) {
    const inner = (error as { error?: { message?: unknown } }).error;
    if (typeof inner?.message === "string") return inner.message;
  }
  return fallback;
}

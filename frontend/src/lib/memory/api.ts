import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type MemoryClaim = components["schemas"]["MemoryResponse"];
export type MemoryHistory = components["schemas"]["MemoryHistoryResponse"];
export type MemoryWrite = components["schemas"]["MemoryWriteRequest"];

export const MEMORY_QUERY_KEY = ["memory", "history"] as const;

export type MemoryFilters = {
  subjectRef?: string;
  asOf?: string;
  believedAt?: string;
  includeRetracted?: boolean;
};

export async function fetchMemoryHistory(
  filters: MemoryFilters = {},
  signal?: AbortSignal,
): Promise<MemoryHistory> {
  const { data, error } = await api.GET("/api/v1/memories", {
    params: {
      query: {
        subject_ref: filters.subjectRef || undefined,
        as_of: filters.asOf || undefined,
        believed_at: filters.believedAt || undefined,
        include_retracted: filters.includeRetracted ?? true,
      },
    },
    signal,
  });
  if (error !== undefined || data === undefined) throw new Error("could not load memory history");
  return data;
}

export async function createMemory(input: MemoryWrite): Promise<MemoryClaim> {
  const { data, error } = await api.POST("/api/v1/memories", { body: input });
  if (error !== undefined || data === undefined) throw new Error("could not save this claim");
  return data.claim;
}

export async function supersedeMemory(id: string, input: MemoryWrite): Promise<MemoryClaim> {
  const { data, error } = await api.POST("/api/v1/memories/{memory_id}/supersede", {
    params: { path: { memory_id: id } },
    body: input,
  });
  if (error !== undefined || data === undefined) throw new Error("could not supersede this claim");
  return data.claim;
}

export async function retractMemory(id: string): Promise<void> {
  const { error } = await api.POST("/api/v1/memories/{memory_id}/retract", {
    params: { path: { memory_id: id } },
  });
  if (error !== undefined) throw new Error("could not retract this claim");
}

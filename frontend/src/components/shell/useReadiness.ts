"use client";

import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { fetchReadiness, type Readiness } from "@/lib/api/readiness";

export const READINESS_QUERY_KEY = ["readiness"] as const;

/**
 * `/readyz`, polled.
 *
 * One query key for the whole app, so the sidebar indicator and the overview
 * list share a single in-flight request instead of racing each other — which is
 * the de-duplication TanStack Query is here for (DesignSystem §5).
 */
export function useReadiness(): UseQueryResult<Readiness, Error> {
  return useQuery({
    queryKey: READINESS_QUERY_KEY,
    queryFn: ({ signal }) => fetchReadiness(signal),
    // Long enough not to be chatter, short enough that a dependency coming back
    // is visible without a reload.
    refetchInterval: 30_000,
  });
}

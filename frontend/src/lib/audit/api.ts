/**
 * The audit log viewer's read: `GET /audit/events`, admin-only at the wire
 * (`audit:read`, granted only by `admin`'s wildcard — TRACKER §5 deliverable
 * 5). A non-admin caller gets a real 403 here, surfaced by the page rather
 * than hidden by the nav.
 */

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type AuditEvent = components["schemas"]["AuditEventResponse"];
export type AuditEventList = components["schemas"]["AuditEventListResponse"];

export type AuditFilters = {
  action?: string;
  resourceKind?: string;
  outcome?: "allow" | "deny";
};

export const AUDIT_EVENTS_QUERY_KEY = ["audit", "events"] as const;

/**
 * The backend's domain-error envelope (`{error: {code, message}}`) is not
 * part of the generated schema — it comes from a global exception handler,
 * not a per-route `response_model` — so the 403 case is recognised at
 * runtime rather than through `openapi-fetch`'s typing.
 */
export class AuditApiError extends Error {
  readonly code: string | undefined;
  constructor(message: string, code: string | undefined) {
    super(message);
    this.code = code;
  }
}

export function isForbidden(error: unknown): error is AuditApiError {
  return error instanceof AuditApiError && error.code === "forbidden";
}

export async function fetchAuditEvents(
  signal: AbortSignal | undefined,
  filters: AuditFilters = {},
): Promise<AuditEventList> {
  const { data, error } = await api.GET("/api/v1/audit/events", {
    signal,
    params: {
      query: {
        action: filters.action || undefined,
        resource_kind: filters.resourceKind || undefined,
        outcome: filters.outcome,
      },
    },
  });
  if (error !== undefined) {
    const body = error as { error?: { code?: string; message?: string } };
    throw new AuditApiError(
      body.error?.message ?? "could not load the audit log",
      body.error?.code,
    );
  }
  return data;
}

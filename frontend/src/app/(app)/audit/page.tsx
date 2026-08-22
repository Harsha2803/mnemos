"use client";

import { useQuery } from "@tanstack/react-query";
import { ScrollText, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { Table, type TableColumn } from "@/components/ui/Table";
import {
  AUDIT_EVENTS_QUERY_KEY,
  fetchAuditEvents,
  isForbidden,
  type AuditEvent,
} from "@/lib/audit/api";

const SELECT = "hit-target rounded-md border border-separator bg-bg px-3 text-callout text-label";
const INPUT = "hit-target w-full rounded-md border border-separator bg-bg px-3 text-callout text-label";

/**
 * Who did what: every security-relevant event this build records (sign-in/
 * sign-out, a tool grant or invocation, a memory supersession or retraction,
 * a document delete, an NL2SQL write refusal), filterable, newest first.
 * Admin-only — `audit:read` is granted only by `admin`'s wildcard
 * (TRACKER §5 deliverable 5) — and a non-admin caller sees exactly that
 * refusal here rather than a generic error screen.
 */
export default function AuditPage() {
  const [action, setAction] = useState("");
  const [resourceKind, setResourceKind] = useState("");
  const [outcome, setOutcome] = useState<"" | "allow" | "deny">("");

  const filters = {
    action: action.trim() || undefined,
    resourceKind: resourceKind.trim() || undefined,
    outcome: outcome === "" ? undefined : outcome,
  };

  const { data, isPending, error } = useQuery({
    queryKey: [...AUDIT_EVENTS_QUERY_KEY, filters],
    queryFn: ({ signal }) => fetchAuditEvents(signal, filters),
  });

  if (isForbidden(error)) {
    return (
      <div className="flex flex-col gap-8">
        <Header />
        <EmptyState
          icon={ShieldAlert}
          title="Only administrators can view the audit log"
          description="Ask an org administrator if you need to review who did what."
          headingLevel={2}
        />
      </div>
    );
  }

  const events = data?.events ?? [];

  return (
    <div className="flex flex-col gap-8">
      <Header />

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(submitEvent) => submitEvent.preventDefault()}
      >
        <label className="flex flex-col gap-1 text-footnote text-label-secondary">
          Action
          <input
            value={action}
            onChange={(changeEvent) => setAction(changeEvent.target.value)}
            placeholder="e.g. auth.sign_in"
            className={INPUT}
          />
        </label>
        <label className="flex flex-col gap-1 text-footnote text-label-secondary">
          Resource kind
          <input
            value={resourceKind}
            onChange={(changeEvent) => setResourceKind(changeEvent.target.value)}
            placeholder="e.g. tool"
            className={INPUT}
          />
        </label>
        <label className="flex flex-col gap-1 text-footnote text-label-secondary">
          Outcome
          <select
            value={outcome}
            onChange={(changeEvent) =>
              setOutcome(changeEvent.target.value as "" | "allow" | "deny")
            }
            className={SELECT}
          >
            <option value="">Any</option>
            <option value="allow">Allow</option>
            <option value="deny">Deny</option>
          </select>
        </label>
      </form>

      <section aria-labelledby="events-heading" className="flex flex-col gap-3">
        <h2 id="events-heading" className="sr-only">
          Audit events
        </h2>
        {isPending ? (
          <div className="flex flex-col gap-2" aria-hidden="true">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : error ? (
          <p role="alert" className="text-callout text-danger">
            {error instanceof Error ? error.message : "could not load the audit log"}
          </p>
        ) : events.length === 0 ? (
          <EmptyState
            icon={ScrollText}
            title="No matching events"
            description="Nothing recorded yet for this filter."
            headingLevel={3}
          />
        ) : (
          <AuditEventTable events={events} />
        )}
      </section>
    </div>
  );
}

function Header() {
  return (
    <header className="flex flex-col gap-2">
      <h1 className="text-large-title font-semibold tracking-title text-label">Audit log</h1>
      <p className="text-callout leading-relaxed text-label-secondary">
        Every security-relevant event this build records — sign-in and sign-out, a tool grant
        or invocation, a memory supersession or retraction, a document delete, and an NL2SQL
        write refusal — who did it, when, and the outcome.
      </p>
    </header>
  );
}

function AuditEventTable({ events }: { events: AuditEvent[] }) {
  const columns: TableColumn<AuditEvent>[] = [
    {
      key: "occurred_at",
      header: "When",
      render: (event) => (
        <time dateTime={event.occurred_at} className="whitespace-nowrap text-footnote">
          {new Date(event.occurred_at).toLocaleString()}
        </time>
      ),
    },
    {
      key: "actor",
      header: "Who",
      render: (event) => (
        <span className="font-mono text-footnote">
          {event.actor_id !== null ? event.actor_id.slice(0, 8) : "system"}
        </span>
      ),
    },
    { key: "action", header: "Action", render: (event) => event.action },
    {
      key: "resource",
      header: "Resource",
      render: (event) => (
        <span className="text-footnote text-label-secondary">
          {event.resource_kind}
          {event.resource_id !== null ? `:${event.resource_id.slice(0, 8)}` : ""}
        </span>
      ),
    },
    {
      key: "outcome",
      header: "Outcome",
      render: (event) => (
        <span
          className={
            event.outcome === "allow"
              ? "font-semibold text-success"
              : "font-semibold text-danger"
          }
        >
          {event.outcome}
        </span>
      ),
    },
    {
      key: "reason",
      header: "Reason",
      render: (event) => (
        <span className="text-footnote text-label-secondary">{event.reason ?? "—"}</span>
      ),
    },
  ];

  return (
    <Table caption="Audit events" columns={columns} rows={events} rowKey={(event) => event.id} />
  );
}

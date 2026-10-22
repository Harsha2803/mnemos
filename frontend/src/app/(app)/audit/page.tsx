"use client";

import { useQuery } from "@tanstack/react-query";
import { ScrollText, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Skeleton } from "@/components/ui/Skeleton";
import { RelativeTime } from "@/components/ui/RelativeTime";
import { Table, type TableColumn } from "@/components/ui/Table";
import {
  AUDIT_EVENTS_QUERY_KEY,
  fetchAuditEvents,
  isForbidden,
  type AuditEvent,
} from "@/lib/audit/api";

const SELECT = "field hit-target";
const INPUT = "field hit-target";

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
        className="grid grid-cols-1 gap-3 @xl/content:grid-cols-3"
        onSubmit={(submitEvent) => submitEvent.preventDefault()}
      >
        <label className="field-label">
          Action
          <input
            value={action}
            onChange={(changeEvent) => setAction(changeEvent.target.value)}
            placeholder="e.g. auth.sign_in"
            className={INPUT}
          />
        </label>
        <label className="field-label">
          Resource kind
          <input
            value={resourceKind}
            onChange={(changeEvent) => setResourceKind(changeEvent.target.value)}
            placeholder="e.g. tool"
            className={INPUT}
          />
        </label>
        <label className="field-label">
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
          <div className="flex flex-col gap-2" role="status" aria-label="Loading audit events">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
          </div>
        ) : error ? (
          <p role="alert" className="border-l-2 border-danger pl-3 text-callout text-danger">
            The audit log could not be loaded ({error instanceof Error ? error.message : "unknown error"}). Your filters are kept; reload to try again.
          </p>
        ) : events.length === 0 ? (
          <EmptyState
            icon={ScrollText}
            title="No matching events"
            description="Nothing recorded matches these filters. Clear one to widen the search."
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
    <PageHeader
      title="Audit log"
      description="Who did what, and whether it was allowed: sign-ins, tool grants and calls, memory revisions, document deletions, and refused SQL writes."
    />
  );
}

function AuditEventTable({ events }: { events: AuditEvent[] }) {
  const columns: TableColumn<AuditEvent>[] = [
    {
      key: "occurred_at",
      header: "When",
      render: (event) => (
        <RelativeTime value={event.occurred_at} form="long" className="whitespace-nowrap text-footnote" />
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
    { key: "action", header: "Action", render: (event) => <span className="font-mono text-footnote">{event.action}</span> },
    {
      key: "resource",
      header: "Resource",
      render: (event) => (
        <span className="font-mono text-footnote text-label-secondary">
          {event.resource_kind}
          {event.resource_id !== null ? `:${event.resource_id.slice(0, 8)}` : ""}
        </span>
      ),
    },
    {
      key: "outcome",
      header: "Outcome",
      render: (event) => (
        <span className={`status-label ${event.outcome === "allow" ? "text-success" : "text-danger"}`}>
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

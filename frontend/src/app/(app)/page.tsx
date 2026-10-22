"use client";

import { useQueries } from "@tanstack/react-query";
import Link from "next/link";
import type { ReactNode } from "react";

import { useReadiness } from "@/components/shell/useReadiness";
import { SystemStatus } from "@/components/shell/SystemStatus";
import { RevisionMark } from "@/components/ui/RevisionMark";
import { Skeleton } from "@/components/ui/Skeleton";
import { fetchSessions, type ChatSession } from "@/lib/chat/api";
import { fetchJobs, fetchSources, type IngestJob } from "@/lib/connectors/api";
import { fetchDocuments, type KnowledgeDocument } from "@/lib/knowledge/api";
import { fetchMemoryHistory, type MemoryHistory } from "@/lib/memory/api";
import { absoluteTime, relativeLong } from "@/lib/time";

/**
 * The overview: where this workspace stands, in one sentence, and what has
 * happened in it, in date order.
 *
 * Not a dashboard of big numbers and quick-action cards. Mnemos is about
 * provenance, so its front page is a ledger: documents ingested (or failed),
 * revisions that superseded older ones, memory claims revised, conversations
 * held — each dated, each linking to where it happened. Readiness is one line,
 * with the per-service detail a press away.
 */
export default function OverviewPage() {
  const [documents, sources, jobs, conversations, memory] = useQueries({
    queries: [
      { queryKey: ["knowledge", "documents"], queryFn: ({ signal }) => fetchDocuments(signal) },
      { queryKey: ["connectors", "sources"], queryFn: ({ signal }) => fetchSources(signal) },
      { queryKey: ["connectors", "jobs"], queryFn: ({ signal }) => fetchJobs(signal) },
      { queryKey: ["chat", "sessions"], queryFn: ({ signal }) => fetchSessions(signal) },
      { queryKey: ["memory", "history", { includeRetracted: true }], queryFn: ({ signal }) => fetchMemoryHistory({ includeRetracted: true }, signal) },
    ],
  });

  const pending = documents.isPending || sources.isPending || jobs.isPending || conversations.isPending;

  return (
    <div className="flex flex-col gap-10">
      <header className="flex flex-col gap-4">
        <h1 className="font-serif text-large-title font-semibold tracking-title text-label">Overview</h1>
        {pending ? (
          <div className="flex flex-col gap-2" role="status" aria-label="Loading the workspace summary">
            <Skeleton className="h-5 w-full max-w-[var(--measure-reading)]" />
            <Skeleton className="h-5 w-2/3 max-w-[var(--measure-reading)]" />
          </div>
        ) : (
          <p className="measure-reading font-serif text-title-3 leading-relaxed text-label">
            <WorkspaceState
              documents={listOrEmpty(documents.data)}
              sourceCount={listOrEmpty(sources.data).filter((source) => source.is_enabled).length}
              jobs={listOrEmpty(jobs.data)}
              sessions={conversations.data?.sessions ?? []}
            />
          </p>
        )}
        <nav aria-label="Start something" className="flex flex-wrap gap-x-6 gap-y-1 text-callout">
          <ActionLink href="/chat">Ask a question</ActionLink>
          <ActionLink href="/knowledge">Add documents</ActionLink>
          <ActionLink href="/sources">Connect a source</ActionLink>
        </nav>
      </header>

      <Readiness />

      <section aria-labelledby="ledger-heading" className="flex flex-col gap-4">
        <h2 id="ledger-heading" className="font-mono text-caption uppercase tracking-caps text-label-secondary">
          Activity
        </h2>
        {pending ? (
          <div className="flex flex-col gap-3" role="status" aria-label="Loading activity">
            {[0, 1, 2, 3].map((row) => (
              <Skeleton key={row} className="h-5 w-full" />
            ))}
          </div>
        ) : (
          <Ledger
            entries={ledgerEntries({
              documents: listOrEmpty(documents.data),
              jobs: listOrEmpty(jobs.data),
              sessions: conversations.data?.sessions ?? [],
              memory: memory.data,
            })}
          />
        )}
        {(documents.isError || jobs.isError || conversations.isError || memory.isError) && (
          <p role="alert" className="text-footnote text-danger">
            Part of the record could not be loaded ({[documents.isError && "documents", jobs.isError && "ingestion", conversations.isError && "conversations", memory.isError && "memory"].filter(Boolean).join(", ")}). What is shown is complete for everything else.
          </p>
        )}
      </section>
    </div>
  );
}

function ActionLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className="hit-target inline-flex items-center font-semibold text-accent underline-offset-4 hover:underline"
    >
      {children} <span aria-hidden="true" className="ml-1">→</span>
    </Link>
  );
}

/** The state of the workspace as one sentence, with its numbers linked to their screens. */
function WorkspaceState({
  documents,
  sourceCount,
  jobs,
  sessions,
}: {
  documents: KnowledgeDocument[];
  sourceCount: number;
  jobs: IngestJob[];
  sessions: ChatSession[];
}) {
  const current = documents.filter((d) => d.status === "ready" && d.superseded_by === null).length;
  const processing = documents.filter((d) => d.status !== "ready" && d.status !== "failed").length;
  const superseded = documents.filter((d) => d.superseded_by !== null).length;
  const running = jobs.filter((j) => j.status === "queued" || j.status === "running").length;
  const failed = jobs.filter((j) => j.status === "failed" || j.status === "stuck").length;
  const latest = sessions
    .map((s) => s.last_message_at ?? s.updated_at)
    .sort()
    .at(-1);

  if (documents.length === 0 && sessions.length === 0) {
    return (
      <>
        An empty workspace. Add a document or connect a source, and Mnemos will answer from it,
        citing the page.
      </>
    );
  }

  return (
    <>
      <Link className="underline decoration-separator underline-offset-4 hover:decoration-accent" href="/knowledge">
        {plural(current, "current document")}
      </Link>
      {processing > 0 && `, ${processing} still processing`}
      {superseded > 0 && `, ${plural(superseded, "superseded revision")} kept on record`}.{" "}
      <Link className="underline decoration-separator underline-offset-4 hover:decoration-accent" href="/sources">
        {plural(sourceCount, "source")}
      </Link>
      {running > 0 || failed > 0
        ? ` connected, with ${[running > 0 && `${running} ingesting`, failed > 0 && `${failed} failed`].filter(Boolean).join(" and ")}.`
        : " connected, nothing ingesting."}{" "}
      {sessions.length > 0
        ? `${plural(sessions.length, "conversation")}, the latest ${latest !== undefined ? relativeLong(latest) : "recently"}.`
        : "No conversations yet."}
    </>
  );
}

/** One line for the API and its dependencies; the per-service list on demand. */
function Readiness() {
  const { data, isPending, isError } = useReadiness();
  const summary = isPending
    ? "Checking services…"
    : isError
      ? "The API is unreachable"
      : data.ready
        ? `All ${data.checks.length} services ready`
        : `${data.checks.filter((check) => !check.ok).length} of ${data.checks.length} services not ready`;
  const tone = isPending ? "bg-fill" : isError ? "bg-danger" : data.ready ? "bg-success" : "bg-warning";

  return (
    <details className="group border-y border-separator" open={!isPending && (isError || !data.ready)}>
      <summary className="hit-target flex cursor-pointer list-none items-center gap-3 text-callout text-label [&::-webkit-details-marker]:hidden">
        <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${tone}`} />
        <span className="flex-1">{summary}</span>
        <span className="text-footnote text-label-secondary group-open:hidden">Details</span>
        <span className="hidden text-footnote text-label-secondary group-open:inline">Hide</span>
      </summary>
      <div className="pb-3">
        <SystemStatus />
      </div>
    </details>
  );
}

type LedgerEntry = {
  key: string;
  at: string;
  kind: "Ingested" | "Failed" | "Ingesting" | "Added" | "Revised" | "Conversation";
  body: ReactNode;
  href?: string;
};

function ledgerEntries({
  documents,
  jobs,
  sessions,
  memory,
}: {
  documents: KnowledgeDocument[];
  jobs: IngestJob[];
  sessions: ChatSession[];
  memory: MemoryHistory | undefined;
}): LedgerEntry[] {
  // A document a job is ingesting (or ingested) is already on the record as
  // that job; listing it again as "Added" would say the same thing twice.
  const fromJobs = new Set(jobs.map((j) => j.document_id).filter(Boolean));
  const jobItems = new Set(jobs.map((j) => j.payload.item_name).filter(Boolean));
  const entries: LedgerEntry[] = [];

  for (const job of jobs) {
    const name = job.payload.item_name ?? job.payload.item_uri ?? job.id;
    const source = job.payload.source_slug;
    if (job.status === "succeeded") {
      entries.push({ key: `job-${job.id}`, at: job.finished_at ?? job.updated_at, kind: "Ingested", href: "/knowledge", body: <>{name}{source && <Muted> from {source}</Muted>}</> });
    } else if (job.status === "failed" || job.status === "stuck") {
      entries.push({ key: `job-${job.id}`, at: job.updated_at, kind: "Failed", href: "/sources", body: <>{name}<Muted> · {job.error_detail ?? job.error_code ?? job.status}</Muted></> });
    } else {
      entries.push({ key: `job-${job.id}`, at: job.updated_at, kind: "Ingesting", href: "/sources", body: <>{name}<Muted> · step {job.done_units} of {job.total_units}</Muted></> });
    }
  }

  for (const document of documents) {
    const replaced = documents.find((other) => other.superseded_by === document.id);
    if (replaced !== undefined) {
      entries.push({
        key: `revision-${document.id}`,
        at: document.created_at,
        kind: "Revised",
        href: "/knowledge",
        body: <RevisionMark previous={replaced.title} current={document.title} />,
      });
    } else if (!fromJobs.has(document.id) && !jobItems.has(document.title) && document.superseded_by === null) {
      entries.push({ key: `doc-${document.id}`, at: document.created_at, kind: "Added", href: "/knowledge", body: document.title });
    }
  }

  const claims = new Map((memory?.claims ?? []).map((claim) => [claim.id, claim]));
  for (const edge of memory?.edges ?? []) {
    const current = claims.get(edge.source_id);
    const previous = claims.get(edge.target_id);
    if (edge.kind !== "supersedes" || current === undefined || previous === undefined) continue;
    entries.push({
      key: `memory-${edge.id}`,
      at: edge.created_at,
      kind: "Revised",
      href: "/memory",
      body: (
        <>
          <Muted>{current.subject.display_name} · {current.predicate} </Muted>
          <RevisionMark previous={previous.object_text} current={current.object_text} />
        </>
      ),
    });
  }

  for (const session of sessions) {
    entries.push({ key: `chat-${session.id}`, at: session.last_message_at ?? session.updated_at, kind: "Conversation", href: `/chat/${session.id}`, body: session.title });
  }

  return entries.sort((left, right) => right.at.localeCompare(left.at)).slice(0, 14);
}

function Ledger({ entries }: { entries: LedgerEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="text-callout text-label-secondary">
        Nothing has happened here yet. Ingest a document or ask a question, and the record starts.
      </p>
    );
  }

  const days = groupByDay(entries);
  return (
    <div className="flex flex-col gap-6">
      {days.map(({ label, entries: dayEntries }) => (
        <section key={label} aria-label={label} className="flex flex-col">
          <h3 className="mb-1 text-footnote font-semibold text-label">{label}</h3>
          <ol className="flex flex-col border-t border-separator">
            {dayEntries.map((entry) => (
              <li key={entry.key} className="border-b border-separator">
                <LedgerRow entry={entry} />
              </li>
            ))}
          </ol>
        </section>
      ))}
    </div>
  );
}

function LedgerRow({ entry }: { entry: LedgerEntry }) {
  const content = (
    <>
      <time dateTime={entry.at} title={absoluteTime(entry.at)} className="w-12 shrink-0 font-mono text-caption text-label-secondary">
        {timeOfDay(entry.at)}
      </time>
      <span className={`w-28 shrink-0 font-mono text-caption uppercase tracking-caps ${KIND_TONE[entry.kind]}`}>{entry.kind}</span>
      <span className="min-w-0 flex-1 text-callout text-label @max-xl/content:basis-full">{entry.body}</span>
    </>
  );
  // On a narrow pane the time and kind share a line and the entry wraps below.
  const row = "flex min-h-11 items-baseline gap-x-3 gap-y-1 py-2.5 @max-xl/content:flex-wrap";
  if (entry.href === undefined) return <div className={row}>{content}</div>;
  return (
    <Link href={entry.href} className={`${row} transition-colors duration-150 ease-standard hover:bg-fill-tertiary`}>
      {content}
    </Link>
  );
}

const KIND_TONE: Record<LedgerEntry["kind"], string> = {
  Ingested: "text-success",
  Failed: "text-danger",
  Ingesting: "text-info",
  Added: "text-label-secondary",
  Revised: "text-rubric",
  Conversation: "text-label-secondary",
};

function Muted({ children }: { children: ReactNode }) {
  return <span className="text-label-secondary">{children}</span>;
}

function groupByDay(entries: LedgerEntry[]): { label: string; entries: LedgerEntry[] }[] {
  const today = new Date();
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate()).getTime();
  const groups = new Map<string, LedgerEntry[]>();
  for (const entry of entries) {
    const at = new Date(entry.at);
    const day = new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime();
    const ago = Math.round((start - day) / 86_400_000);
    const label =
      ago <= 0
        ? "Today"
        : ago === 1
          ? "Yesterday"
          : new Intl.DateTimeFormat(undefined, { weekday: "long", day: "numeric", month: "long", year: at.getFullYear() === today.getFullYear() ? undefined : "numeric" }).format(at);
    groups.set(label, [...(groups.get(label) ?? []), entry]);
  }
  return [...groups.entries()].map(([label, grouped]) => ({ label, entries: grouped }));
}

function timeOfDay(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" }).format(new Date(iso));
}

function plural(count: number, noun: string): string {
  return `${count === 0 ? "No" : count} ${noun}${count === 1 ? "" : "s"}`;
}

function listOrEmpty<T>(value: T[] | undefined): T[] {
  return Array.isArray(value) ? value : [];
}

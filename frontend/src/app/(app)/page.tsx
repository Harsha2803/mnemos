"use client";

import { useQueries } from "@tanstack/react-query";
import { ArrowRight, BookOpen, MessageCircle, Plug, Upload } from "lucide-react";
import Link from "next/link";

import { SystemStatus } from "@/components/shell/SystemStatus";
import { Skeleton } from "@/components/ui/Skeleton";
import { fetchSessions } from "@/lib/chat/api";
import { fetchJobs, fetchSources } from "@/lib/connectors/api";
import { fetchDocuments } from "@/lib/knowledge/api";

export default function OverviewPage() {
  const [documents, sources, jobs, conversations] = useQueries({
    queries: [
      { queryKey: ["knowledge", "documents"], queryFn: ({ signal }) => fetchDocuments(signal) },
      { queryKey: ["connectors", "sources"], queryFn: ({ signal }) => fetchSources(signal) },
      { queryKey: ["connectors", "jobs"], queryFn: ({ signal }) => fetchJobs(signal) },
      { queryKey: ["chat", "sessions"], queryFn: ({ signal }) => fetchSessions(signal) },
    ],
  });

  const activeJobs = (jobs.data ?? []).filter((job) => ["queued", "running", "stuck"].includes(job.status));
  const readyDocuments = (documents.data ?? []).filter((document) => document.status === "ready");
  const enabledSources = (sources.data ?? []).filter((source) => source.is_enabled);

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-title-1 font-semibold tracking-title text-label">Overview</h1>
        <p className="text-callout text-label-secondary">What Mnemos can use, what is processing, and where to continue.</p>
      </header>

      <section className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-separator bg-separator sm:grid-cols-4" aria-label="Workspace summary">
        <SummaryMetric label="Ready documents" value={readyDocuments.length} pending={documents.isPending} />
        <SummaryMetric label="Enabled sources" value={enabledSources.length} pending={sources.isPending} />
        <SummaryMetric label="Active jobs" value={activeJobs.length} pending={jobs.isPending} />
        <SummaryMetric label="Conversations" value={conversations.data?.sessions.length ?? 0} pending={conversations.isPending} />
      </section>

      <section className="flex flex-col gap-3" aria-labelledby="quick-actions-heading">
        <h2 id="quick-actions-heading" className="text-title-3 font-semibold tracking-title">Quick actions</h2>
        <div className="grid gap-2 sm:grid-cols-3">
          <QuickAction href="/chat" icon={MessageCircle} label="New chat" detail="Ask Mnemos a question" />
          <QuickAction href="/knowledge" icon={Upload} label="Upload documents" detail="Add knowledge to search" />
          <QuickAction href="/sources" icon={Plug} label="Connect source" detail="Browse and ingest a source" />
        </div>
      </section>

      <div className="grid gap-8 lg:grid-cols-2">
        <section className="flex flex-col gap-3" aria-labelledby="recent-ingestion-heading">
          <h2 id="recent-ingestion-heading" className="text-title-3 font-semibold tracking-title">Recent ingestion</h2>
          {jobs.isPending ? <Skeleton className="h-24 w-full" /> : (jobs.data ?? []).length === 0 ? (
            <CompactEmpty icon={Plug} text="No ingestion activity yet." href="/sources" action="Connect a source" />
          ) : (
            <ul className="divide-y divide-separator rounded-md border border-separator">
              {(jobs.data ?? []).slice(0, 4).map((job) => (
                <li key={job.id} className="flex items-center justify-between gap-3 px-3 py-2 text-footnote">
                  <span className="min-w-0 truncate text-label">{job.payload.item_name ?? job.payload.item_uri ?? job.id}</span>
                  <span className={statusTone(job.status)}>{statusLabel(job.status)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="flex flex-col gap-3" aria-labelledby="recent-conversations-heading">
          <h2 id="recent-conversations-heading" className="text-title-3 font-semibold tracking-title">Recent conversations</h2>
          {conversations.isPending ? <Skeleton className="h-24 w-full" /> : (conversations.data?.sessions.length ?? 0) === 0 ? (
            <CompactEmpty icon={MessageCircle} text="No conversations yet." href="/chat" action="Start a chat" />
          ) : (
            <ul className="divide-y divide-separator rounded-md border border-separator">
              {conversations.data?.sessions.slice(0, 4).map((session) => (
                <li key={session.id}>
                  <Link href={`/chat/${session.id}`} className="hit-target flex items-center justify-between gap-3 px-3 py-2 text-footnote hover:bg-fill-tertiary">
                    <span className="truncate text-label">{session.title}</span>
                    <ArrowRight className="size-4 shrink-0 text-label-tertiary" aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="flex flex-col gap-3" aria-labelledby="system-status-heading">
        <h2 id="system-status-heading" className="text-title-3 font-semibold tracking-title">System readiness</h2>
        <SystemStatus />
      </section>
    </div>
  );
}

function SummaryMetric({ label, value, pending }: { label: string; value: number; pending: boolean }) {
  return (
    <div className="bg-bg-secondary p-4">
      {pending ? <Skeleton className="h-7 w-12" /> : <span className="text-title-2 font-semibold text-label">{value}</span>}
      <span className="mt-1 block text-footnote text-label-secondary">{label}</span>
    </div>
  );
}

function QuickAction({ href, icon: Icon, label, detail }: { href: string; icon: typeof BookOpen; label: string; detail: string }) {
  return (
    <Link href={href} aria-label={label === "New chat" ? "Start new conversation" : undefined} className="hit-target flex items-center gap-3 rounded-md border border-separator p-3 hover:bg-fill-tertiary">
      <Icon className="size-5 shrink-0 text-accent" strokeWidth={1.5} aria-hidden="true" />
      <span className="min-w-0">
        <span className="block text-callout font-semibold text-label">{label}</span>
        <span className="block text-footnote text-label-secondary">{detail}</span>
      </span>
    </Link>
  );
}

function CompactEmpty({ icon: Icon, text, href, action }: { icon: typeof BookOpen; text: string; href: string; action: string }) {
  return (
    <div className="flex items-center gap-3 rounded-md border border-separator p-4">
      <Icon className="size-5 text-label-tertiary" aria-hidden="true" />
      <p className="text-footnote text-label-secondary">{text} <Link className="font-semibold text-accent" href={href}>{action}</Link></p>
    </div>
  );
}

function statusLabel(status: string): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function statusTone(status: string): string {
  if (status === "succeeded") return "shrink-0 font-semibold text-success";
  if (status === "failed") return "shrink-0 font-semibold text-danger";
  if (status === "stuck") return "shrink-0 font-semibold text-warning";
  return "shrink-0 font-semibold text-info";
}

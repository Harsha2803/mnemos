"use client";

import { AlertTriangle, Check, CheckCircle2, ChevronDown, Clock, Copy, Loader2, XCircle, type LucideIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";

export type FeedJobStatus = "queued" | "running" | "succeeded" | "failed" | "stuck";
export type FeedJobEvent = { id: string; fromStatus: string | null; toStatus: string; ownerId: string | null; detail: string | null; occurredAt: string };

export type FeedJob = {
  jobId: string;
  itemName: string;
  status: FeedJobStatus;
  errorCode: string | null;
  errorDetail: string | null;
  attempts: number | null;
  maxAttempts: number | null;
  doneUnits: number | null;
  totalUnits: number | null;
  updatedAt: string;
  events: FeedJobEvent[];
  ownerId: string | null;
  heartbeatAt: string | null;
  leaseExpiresAt: string | null;
  startedAt: string | null;
  finishedAt: string | null;
};

export type EventFeedProps = { jobs: FeedJob[] };
type FeedFilter = "active" | "failed" | "succeeded" | "all";

const STATUS: Record<FeedJobStatus, { icon: LucideIcon; label: string; tone: string }> = {
  queued: { icon: Clock, label: "Queued", tone: "text-label-secondary" },
  running: { icon: Loader2, label: "Running", tone: "text-info" },
  succeeded: { icon: CheckCircle2, label: "Succeeded", tone: "text-success" },
  failed: { icon: XCircle, label: "Failed", tone: "text-danger" },
  stuck: { icon: AlertTriangle, label: "Stuck", tone: "text-warning" },
};

export function EventFeed({ jobs }: EventFeedProps) {
  const [filter, setFilter] = useState<FeedFilter>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState<string | null>(null);

  if (jobs.length === 0) {
    return <EmptyState icon={Clock} title="Nothing queued yet" description="Ingest an item above and its progress appears here live." headingLevel={3} />;
  }

  const visible = jobs.filter((job) => {
    if (filter === "active") return ["queued", "running"].includes(job.status);
    if (filter === "failed") return ["failed", "stuck"].includes(job.status);
    if (filter === "succeeded") return job.status === "succeeded";
    return true;
  });

  async function copyId(jobId: string): Promise<void> {
    await navigator.clipboard.writeText(jobId);
    setCopied(jobId);
    window.setTimeout(() => setCopied(null), 1500);
  }

  function toggle(jobId: string): void {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(jobId)) next.delete(jobId); else next.add(jobId);
      return next;
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1" role="group" aria-label="Filter ingestion activity">
        {(["all", "active", "failed", "succeeded"] as const).map((value) => (
          <button key={value} type="button" aria-pressed={filter === value} onClick={() => setFilter(value)} className="hit-target !min-h-9 rounded-full px-3 text-footnote font-semibold capitalize text-label-secondary hover:bg-fill-tertiary aria-pressed:bg-accent-tint aria-pressed:text-accent">
            {value}
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <p className="rounded-md border border-separator p-4 text-footnote text-label-secondary">No jobs match this filter.</p>
      ) : (
        <ul aria-label="Ingestion activity" className="flex flex-col gap-2">
          {visible.map((job) => {
            const { icon: Icon, label, tone } = STATUS[job.status];
            const progress = job.totalUnits !== null && job.totalUnits > 0 && job.doneUnits !== null ? Math.min(100, Math.round((job.doneUnits / job.totalUnits) * 100)) : null;
            const attempts = job.attempts !== null && job.maxAttempts !== null ? `Attempt ${job.attempts}/${job.maxAttempts}` : null;
            const open = expanded.has(job.jobId);
            return (
              <li key={job.jobId} className="rounded-md border border-separator bg-bg-secondary">
                <div className="flex items-start gap-3 px-4 py-3">
                  <Icon className={`mt-0.5 size-[18px] shrink-0 ${tone} ${job.status === "running" ? "animate-spin" : ""}`} strokeWidth={1.5} aria-hidden="true" />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-callout text-label">{job.itemName}</span>
                    <span className="text-footnote text-label-secondary">{[attempts, progress !== null ? `${progress}%` : null, relativeTime(job.updatedAt)].filter(Boolean).join(" · ")}</span>
                    {progress !== null && (
                      <span role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress} aria-label={`${job.itemName} progress`} className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-fill">
                        <span className="block h-full rounded-full bg-accent" style={{ width: `${progress}%` }} />
                      </span>
                    )}
                    {(job.status === "failed" || job.status === "stuck") && job.errorCode !== null && (
                      <span className="mt-1 text-footnote text-label-secondary">Error: {job.errorCode}{job.errorDetail ? ` — ${job.errorDetail}` : ""}</span>
                    )}
                  </div>
                  <span className={`shrink-0 text-footnote font-semibold ${tone}`}>{label}</span>
                  <Button rank="plain" aria-label={`${open ? "Collapse" : "Expand"} ${job.itemName} history`} aria-expanded={open} className="!px-2" onClick={() => toggle(job.jobId)}>
                    <ChevronDown className={`size-4 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
                  </Button>
                </div>
                {open && <JobDetails job={job} copied={copied === job.jobId} onCopy={() => void copyId(job.jobId)} />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

function JobDetails({ job, copied, onCopy }: { job: FeedJob; copied: boolean; onCopy: () => void }) {
  return (
    <div className="border-t border-separator px-4 py-4">
      <div className="mb-4 flex items-center justify-between gap-2">
        <code className="min-w-0 truncate text-caption text-label-secondary">{job.jobId}</code>
        <Button rank="plain" aria-label="Copy job ID" className="!min-h-9 !px-2 text-footnote" onClick={onCopy}>
          {copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}{copied ? "Copied" : "Copy ID"}
        </Button>
      </div>
      <dl className="mb-4 grid gap-3 text-footnote sm:grid-cols-2">
        <Detail label="Owner" value={job.ownerId ?? "Unassigned"} />
        <Detail label="Started" value={formatTimestamp(job.startedAt)} />
        <Detail label="Last heartbeat" value={formatTimestamp(job.heartbeatAt)} />
        <Detail label="Lease expires" value={formatTimestamp(job.leaseExpiresAt)} />
        <Detail label="Finished" value={formatTimestamp(job.finishedAt)} />
      </dl>
      <ol className="relative ml-2 border-l border-separator pl-5" aria-label="Job status history">
        {(job.events.length > 0 ? job.events : [{ id: `current-${job.jobId}`, fromStatus: null, toStatus: job.status, ownerId: job.ownerId, detail: job.errorDetail, occurredAt: job.updatedAt }]).map((event) => (
          <li key={event.id} className="relative pb-4 last:pb-0">
            <span className="absolute -left-[1.55rem] top-1 size-2 rounded-full bg-accent" aria-hidden="true" />
            <span className="block text-footnote font-semibold text-label">{statusLabel(event.toStatus)}</span>
            <time className="text-caption text-label-secondary" dateTime={event.occurredAt}>{formatTimestamp(event.occurredAt)}</time>
            {event.detail && <p className="mt-1 text-footnote text-label-secondary">{event.detail}</p>}
          </li>
        ))}
      </ol>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) { return <div><dt className="text-caption text-label-secondary">{label}</dt><dd className="mt-0.5 truncate text-label">{value}</dd></div>; }
function statusLabel(value: string): string { return value.charAt(0).toUpperCase() + value.slice(1); }
function formatTimestamp(value: string | null): string { return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)) : "—"; }
function relativeTime(value: string): string { const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000)); if (seconds < 60) return "just now"; if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`; if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`; return `${Math.floor(seconds / 86400)}d ago`; }

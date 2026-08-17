import { CheckCircle2, Clock, Loader2, XCircle, type LucideIcon } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";

export type FeedJobStatus = "queued" | "running" | "succeeded" | "failed";

export type FeedJob = {
  jobId: string;
  itemName: string;
  status: FeedJobStatus;
  errorCode: string | null;
};

export type EventFeedProps = {
  jobs: FeedJob[];
};

/**
 * Icon *and* plain-word label for every state — never colour alone
 * (DesignSystem §3, the same discipline `SqlPanel.tsx`'s denial banner
 * established). `queued` is the UI's own optimistic state (TRACKER §5
 * deliverable 4 recap: the worker never publishes a `queued` transition);
 * everything after it is a real WebSocket message.
 */
const STATUS: Record<FeedJobStatus, { icon: LucideIcon; label: string; tone: string }> = {
  queued: { icon: Clock, label: "Queued", tone: "text-label-secondary" },
  running: { icon: Loader2, label: "Running", tone: "text-info" },
  succeeded: { icon: CheckCircle2, label: "Succeeded", tone: "text-success" },
  failed: { icon: XCircle, label: "Failed", tone: "text-danger" },
};

export function EventFeed({ jobs }: EventFeedProps) {
  if (jobs.length === 0) {
    return (
      <EmptyState
        icon={Clock}
        title="Nothing queued yet"
        description="Ingest an item above and its progress appears here live."
        headingLevel={3}
      />
    );
  }

  return (
    <ul aria-label="Ingestion activity" className="flex flex-col gap-2">
      {jobs.map((job) => {
        const { icon: Icon, label, tone } = STATUS[job.status];
        return (
          <li
            key={job.jobId}
            className="flex items-center gap-3 rounded-md border border-separator bg-bg-secondary px-4 py-3"
          >
            <Icon
              className={`size-[18px] shrink-0 ${tone} ${job.status === "running" ? "animate-spin" : ""}`}
              strokeWidth={1.5}
              aria-hidden="true"
            />
            <div className="flex min-w-0 flex-1 flex-col">
              <span className="truncate text-callout text-label">{job.itemName}</span>
              {job.status === "failed" && job.errorCode !== null && (
                <span className="text-footnote text-label-secondary">Error: {job.errorCode}</span>
              )}
            </div>
            <span className={`shrink-0 text-footnote font-semibold ${tone}`}>{label}</span>
          </li>
        );
      })}
    </ul>
  );
}

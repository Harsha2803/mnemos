"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";

import { EventFeed, type FeedJob, type FeedJobStatus } from "@/components/connectors/EventFeed";
import { ItemBrowser } from "@/components/connectors/ItemBrowser";
import { RegisterSourceForm } from "@/components/connectors/RegisterSourceForm";
import { SourceList } from "@/components/connectors/SourceList";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  CONNECTOR_JOBS_QUERY_KEY,
  fetchItems,
  fetchJobs,
  fetchSources,
  type IngestJob,
  ingestItem,
  itemsQueryKey,
  SOURCES_QUERY_KEY,
} from "@/lib/connectors/api";
import { useIngestionFeed, type IngestionEvent } from "@/lib/connectors/realtime";

export default function SourcesPage() {
  const queryClient = useQueryClient();
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);
  const [jobs, setJobs] = useState<Record<string, FeedJob>>({});

  const sources = useQuery({
    queryKey: SOURCES_QUERY_KEY,
    queryFn: ({ signal }) => fetchSources(signal),
  });

  const items = useQuery({
    queryKey: selectedSlug === null ? itemsQueryKey("") : itemsQueryKey(selectedSlug),
    queryFn: ({ signal }) => fetchItems(selectedSlug as string, signal),
    enabled: selectedSlug !== null,
  });

  const recentJobs = useQuery({
    queryKey: CONNECTOR_JOBS_QUERY_KEY,
    queryFn: ({ signal }) => fetchJobs(signal),
  });

  useEffect(() => {
    if (!recentJobs.data) return;
    setJobs((current) => {
      const next = { ...current };
      for (const job of recentJobs.data) {
        next[job.id] = mergeJob(next[job.id], feedJobFromRecord(job));
      }
      return next;
    });
  }, [recentJobs.data]);

  const onIngestionEvent = useCallback((event: IngestionEvent) => {
    setJobs((current) => ({
      ...current,
      [event.job_id]: mergeJob(current[event.job_id], {
        jobId: event.job_id,
        itemName: current[event.job_id]?.itemName ?? event.job_id,
        status: event.status,
        errorCode: event.error_code ?? null,
        errorDetail: event.error_detail ?? null,
        attempts: event.attempts ?? null,
        maxAttempts: event.max_attempts ?? null,
        doneUnits: event.done_units ?? null,
        totalUnits: event.total_units ?? null,
        updatedAt: event.occurred_at,
        events: current[event.job_id]?.events ?? [],
        ownerId: current[event.job_id]?.ownerId ?? null,
        heartbeatAt: current[event.job_id]?.heartbeatAt ?? null,
        leaseExpiresAt: current[event.job_id]?.leaseExpiresAt ?? null,
        startedAt: current[event.job_id]?.startedAt ?? null,
        finishedAt: current[event.job_id]?.finishedAt ?? null,
      }),
    }));
  }, []);

  useIngestionFeed(onIngestionEvent);

  const ingest = useMutation({
    mutationFn: async (uris: string[]) => {
      if (selectedSlug === null) return;
      for (const uri of uris) {
        const matched = items.data?.find((item) => item.uri === uri);
        const response = await ingestItem(selectedSlug, uri);
        setJobs((current) => ({
          ...current,
          [response.job_id]: mergeJob(current[response.job_id], {
            jobId: response.job_id,
            itemName: matched?.name ?? uri,
            status: "queued",
            errorCode: null,
            errorDetail: null,
            attempts: 0,
            maxAttempts: null,
            doneUnits: 0,
            totalUnits: 4,
            updatedAt: new Date().toISOString(),
            events: [],
            ownerId: null,
            heartbeatAt: null,
            leaseExpiresAt: null,
            startedAt: null,
            finishedAt: null,
          }),
        }));
      }
      void queryClient.invalidateQueries({ queryKey: CONNECTOR_JOBS_QUERY_KEY });
    },
  });

  const selectedSource = sources.data?.find((source) => source.slug === selectedSlug) ?? null;
  const lastActivityBySlug = (recentJobs.data ?? []).reduce<Record<string, string>>((result, job) => {
    const slug = job.payload.source_slug;
    if (slug && (!result[slug] || job.updated_at > result[slug])) result[slug] = job.updated_at;
    return result;
  }, {});
  const feedJobs = Object.values(jobs).sort((left, right) =>
    right.updatedAt.localeCompare(left.updatedAt),
  );

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-large-title font-semibold tracking-title text-label">Sources</h1>
        <p className="text-callout leading-relaxed text-label-secondary">
          Connect a bucket, a filesystem directory or a curated list of URLs, browse what it
          contains, and ingest items into the knowledge library. Progress arrives live below.
        </p>
      </header>

      <section className="flex flex-col gap-3" aria-labelledby="register-heading">
        <h2 id="register-heading" className="text-title-3 font-semibold tracking-title">
          Connect a source
        </h2>
        <RegisterSourceForm
          onRegistered={() => void queryClient.invalidateQueries({ queryKey: SOURCES_QUERY_KEY })}
        />
      </section>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)]">
        <section className="flex flex-col gap-3" aria-labelledby="sources-heading">
          <h2 id="sources-heading" className="text-title-3 font-semibold tracking-title">
            Registered sources
          </h2>
          {sources.isPending ? (
            <div className="flex flex-col gap-2" aria-hidden="true">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : (
            <SourceList
              sources={sources.data ?? []}
              selectedSlug={selectedSlug}
              onSelect={setSelectedSlug}
              lastActivityBySlug={lastActivityBySlug}
            />
          )}
        </section>

        <section className="flex flex-col gap-3" aria-labelledby="items-heading">
          <h2 id="items-heading" className="text-title-3 font-semibold tracking-title">
            {selectedSource ? `Items at ${selectedSource.name}` : "Browse a source"}
          </h2>
          {selectedSlug === null ? (
            <p className="text-callout text-label-secondary">
              Select a registered source to browse what it contains.
            </p>
          ) : items.isPending ? (
            <div className="flex flex-col gap-2" aria-hidden="true">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : (
            <ItemBrowser
              sourceName={selectedSource?.name ?? selectedSlug}
              items={items.data ?? []}
              onIngest={(uris) => ingest.mutateAsync(uris)}
            />
          )}
        </section>
      </div>

      <section className="flex flex-col gap-3" aria-labelledby="activity-heading">
        <h2 id="activity-heading" className="text-title-3 font-semibold tracking-title">
          Ingestion activity
        </h2>
        {recentJobs.isPending && feedJobs.length === 0 ? (
          <div className="flex flex-col gap-2" aria-hidden="true">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        ) : (
          <EventFeed jobs={feedJobs} />
        )}
      </section>
    </div>
  );
}

function feedJobFromRecord(job: IngestJob): FeedJob {
  const lastEvent = job.events.at(-1);
  return {
    jobId: job.id,
    itemName: job.payload.item_name ?? job.payload.item_uri ?? job.id,
    status: asFeedStatus(job.status),
    errorCode: job.error_code,
    errorDetail: job.error_detail ?? lastEvent?.detail ?? null,
    attempts: job.attempts,
    maxAttempts: job.max_attempts,
    doneUnits: job.done_units,
    totalUnits: job.total_units,
    updatedAt: job.updated_at,
    events: job.events.map((event) => ({
      id: event.id,
      fromStatus: event.from_status,
      toStatus: event.to_status,
      ownerId: event.owner_id,
      detail: event.detail,
      occurredAt: event.occurred_at,
    })),
    ownerId: job.owner_id,
    heartbeatAt: job.heartbeat_at,
    leaseExpiresAt: job.lease_expires_at,
    startedAt: job.started_at,
    finishedAt: job.finished_at,
  };
}

function mergeJob(previous: FeedJob | undefined, next: FeedJob): FeedJob {
  return {
    ...next,
    itemName: previous?.itemName ?? next.itemName,
    errorCode: next.errorCode ?? previous?.errorCode ?? null,
    errorDetail: next.errorDetail ?? previous?.errorDetail ?? null,
    attempts: next.attempts ?? previous?.attempts ?? null,
    maxAttempts: next.maxAttempts ?? previous?.maxAttempts ?? null,
    doneUnits: next.doneUnits ?? previous?.doneUnits ?? null,
    totalUnits: next.totalUnits ?? previous?.totalUnits ?? null,
    events: next.events.length > 0 ? next.events : previous?.events ?? [],
    ownerId: next.ownerId ?? previous?.ownerId ?? null,
    heartbeatAt: next.heartbeatAt ?? previous?.heartbeatAt ?? null,
    leaseExpiresAt: next.leaseExpiresAt ?? previous?.leaseExpiresAt ?? null,
    startedAt: next.startedAt ?? previous?.startedAt ?? null,
    finishedAt: next.finishedAt ?? previous?.finishedAt ?? null,
  };
}

function asFeedStatus(status: string): FeedJobStatus {
  if (
    status === "queued" ||
    status === "running" ||
    status === "succeeded" ||
    status === "failed" ||
    status === "stuck"
  ) {
    return status;
  }
  return "failed";
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { EventFeed, type FeedJob } from "@/components/connectors/EventFeed";
import { ItemBrowser } from "@/components/connectors/ItemBrowser";
import { RegisterSourceForm } from "@/components/connectors/RegisterSourceForm";
import { SourceList } from "@/components/connectors/SourceList";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  fetchItems,
  fetchSources,
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

  const onIngestionEvent = useCallback((event: IngestionEvent) => {
    setJobs((current) => ({
      ...current,
      [event.job_id]: {
        jobId: event.job_id,
        itemName: current[event.job_id]?.itemName ?? event.job_id,
        status: event.status,
        errorCode: event.error_code,
      },
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
          [response.job_id]: {
            jobId: response.job_id,
            itemName: matched?.name ?? uri,
            status: "queued",
            errorCode: null,
          },
        }));
      }
    },
  });

  const selectedSource = sources.data?.find((source) => source.slug === selectedSlug) ?? null;
  const feedJobs = Object.values(jobs).reverse();

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
        <EventFeed jobs={feedJobs} />
      </section>
    </div>
  );
}

"use client";

import { FolderOpen } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { List, ListItem } from "@/components/ui/List";
import { relativeLong } from "@/lib/time";
import type { ContentSource } from "@/lib/connectors/api";

export type SourceListProps = {
  sources: ContentSource[];
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
  lastActivityBySlug?: Record<string, string>;
};

const KIND_LABEL: Record<string, string> = {
  s3: "S3",
  minio: "S3-compatible",
  local_fs: "Directory",
  http: "URL list",
};

export function SourceList({ sources, selectedSlug, onSelect, lastActivityBySlug = {} }: SourceListProps) {
  if (sources.length === 0) {
    return (
      <EmptyState
        icon={FolderOpen}
        title="No sources registered yet"
        description="Connect one above: a bucket, a directory the operator has approved, or a list of URLs."
        headingLevel={3}
      />
    );
  }

  return (
    <List label="Sources">
      {sources.map((source) => {
        const lastActivity = lastActivityBySlug[source.slug];
        const selected = source.slug === selectedSlug;
        return (
          <ListItem key={source.id} current={selected}>
            <button
              type="button"
              onClick={() => onSelect(source.slug)}
              aria-current={selected ? "true" : undefined}
              className={[
                "hit-target relative block w-full py-1 pl-3 text-left",
                "before:absolute before:inset-y-2 before:left-0 before:w-0.5 before:rounded-full",
                selected ? "before:bg-rubric" : "before:bg-transparent",
              ].join(" ")}
            >
              <span className={`block truncate ${selected ? "font-semibold" : "font-medium"} text-label`}>{source.name}</span>
              <span className="block font-mono text-caption text-label-secondary">
                {source.slug} · {KIND_LABEL[source.kind] ?? source.kind}
              </span>
              <span className="block text-caption text-label-secondary">
                {source.is_enabled ? "Enabled" : "Disabled"} · added {relativeLong(source.created_at)}
                {lastActivity ? ` · last activity ${relativeLong(lastActivity)}` : ""}
              </span>
            </button>
          </ListItem>
        );
      })}
    </List>
  );
}



"use client";

import { Database, FolderOpen, Globe } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { List, ListItem } from "@/components/ui/List";
import type { ContentSource } from "@/lib/connectors/api";

export type SourceListProps = {
  sources: ContentSource[];
  selectedSlug: string | null;
  onSelect: (slug: string) => void;
};

const KIND_ICON: Record<string, LucideIcon> = {
  s3: Database,
  minio: Database,
  local_fs: FolderOpen,
  http: Globe,
};

export function SourceList({ sources, selectedSlug, onSelect }: SourceListProps) {
  if (sources.length === 0) {
    return (
      <EmptyState
        icon={FolderOpen}
        title="No sources registered yet"
        description="Register one above, then browse what it contains."
        headingLevel={3}
      />
    );
  }

  return (
    <List label="Sources">
      {sources.map((source) => {
        const Icon = KIND_ICON[source.kind] ?? FolderOpen;
        return (
          <ListItem
            key={source.id}
            leading={<Icon className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />}
            current={source.slug === selectedSlug}
          >
            <button
              type="button"
              onClick={() => onSelect(source.slug)}
              aria-current={source.slug === selectedSlug ? "true" : undefined}
              className="block w-full text-left"
            >
              <span className="block truncate font-medium text-label">{source.name}</span>
              <span className="block text-footnote text-label-secondary">
                {source.slug} · {source.kind}
              </span>
            </button>
          </ListItem>
        );
      })}
    </List>
  );
}

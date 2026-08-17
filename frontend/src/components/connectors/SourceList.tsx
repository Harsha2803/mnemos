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
  lastActivityBySlug?: Record<string, string>;
};

const KIND_ICON: Record<string, LucideIcon> = {
  s3: Database,
  minio: Database,
  local_fs: FolderOpen,
  http: Globe,
};

export function SourceList({ sources, selectedSlug, onSelect, lastActivityBySlug = {} }: SourceListProps) {
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
        const lastActivity = lastActivityBySlug[source.slug];
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
              <span className="block text-caption text-label-tertiary">
                {source.is_enabled ? "Enabled" : "Disabled"} · Added {formatDate(source.created_at)}
                {lastActivity ? ` · Active ${relativeTime(lastActivity)}` : ""}
              </span>
            </button>
          </ListItem>
        );
      })}
    </List>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
}

function relativeTime(value: string): string {
  const minutes = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h ago`;
  return `${Math.floor(minutes / 1440)}d ago`;
}

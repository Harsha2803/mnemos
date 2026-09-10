"use client";

import { FileQuestion, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Table } from "@/components/ui/Table";
import { EmptyState } from "@/components/ui/EmptyState";
import type { SourceItem } from "@/lib/connectors/api";

export type ItemBrowserProps = {
  sourceName: string;
  items: SourceItem[];
  onIngest: (uris: string[]) => Promise<void>;
};

/**
 * Browse, select, ingest — the middle third of the milestone's sentence
 * (TRACKER §5). Selection is a plain checkbox column rather than a second
 * confirmation dialog: ingesting is additive and idempotent per item
 * (`idempotency_key`), not destructive, so it does not need the weight
 * `DocumentList.tsx`'s delete confirmation carries (DesignSystem §4).
 */
export function ItemBrowser({ sourceName, items, onIngest }: ItemBrowserProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [type, setType] = useState("all");

  const types = useMemo(() => [...new Set(items.map((item) => item.content_type))].sort(), [items]);
  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return items.filter((item) =>
      (type === "all" || item.content_type === type) &&
      (normalized.length === 0 || item.name.toLocaleLowerCase().includes(normalized)),
    );
  }, [items, query, type]);

  if (items.length === 0) {
    return (
      <EmptyState
        icon={FileQuestion}
        title={`${sourceName} has nothing to ingest`}
        description="Nothing is currently listed at this source."
        headingLevel={3}
      />
    );
  }

  function toggle(uri: string): void {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(uri)) next.delete(uri);
      else next.add(uri);
      return next;
    });
  }

  function toggleVisible(): void {
    const allVisibleSelected = visible.length > 0 && visible.every((item) => selected.has(item.uri));
    setSelected((current) => {
      const next = new Set(current);
      for (const item of visible) {
        if (allVisibleSelected) next.delete(item.uri); else next.add(item.uri);
      }
      return next;
    });
  }

  async function ingestSelected(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await onIngest([...selected]);
      setSelected(new Set());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "could not queue the selected items");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-2 @xl/content:grid-cols-[minmax(0,1fr)_auto]">
        <label className="relative">
          <span className="sr-only">Search source items</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-label-tertiary" aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search items" className="hit-target w-full rounded-md border border-separator bg-bg pl-10 pr-3 text-callout text-label" />
        </label>
        <label>
          <span className="sr-only">Filter item type</span>
          <select value={type} onChange={(event) => setType(event.target.value)} className="hit-target w-full min-w-0 rounded-md border border-separator bg-bg px-3 text-callout text-label">
            <option value="all">All file types</option>
            {types.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
      </div>

      <p role="alert" className="text-footnote text-danger empty:hidden">
        {error ?? ""}
      </p>

      {visible.length === 0 ? (
        <p className="rounded-md border border-separator p-4 text-footnote text-label-secondary">No source items match these filters.</p>
      ) : <Table
        caption={`Items at ${sourceName}`}
        rows={visible}
        rowKey={(item) => item.uri}
        columns={[
          { key: "name", header: "Name", render: (item) => (
            <label className="hit-target flex cursor-pointer items-center gap-3 font-semibold">
              <input type="checkbox" checked={selected.has(item.uri)} onChange={() => toggle(item.uri)} aria-label={`Select ${item.name}`} className="size-[18px] shrink-0" />
              <span className="min-w-0">{item.name}</span>
            </label>
          ) },
          { key: "type", header: "Type", render: (item) => item.content_type },
          { key: "size", header: "Size", render: (item) => formatBytes(item.size_bytes) },
          { key: "modified", header: "Modified", render: (item) => formatDate(item.modified_at) },
        ]}
      />}
      <div className="selection-bar sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-2 border-t border-separator bg-bg py-2">
        <label className="hit-target flex cursor-pointer items-center gap-2 text-footnote">
          <input type="checkbox" checked={visible.length > 0 && visible.every((item) => selected.has(item.uri))} disabled={visible.length === 0 || busy} onChange={toggleVisible} aria-label="Select all visible items" className="size-[18px]" />
          Select visible
        </label>
        <p role="status" className="text-footnote text-label-secondary">{selected.size} selected · {visible.length} visible</p>
        <Button rank="filled" disabled={selected.size === 0 || busy} aria-busy={busy} onClick={() => void ingestSelected()}>
          {busy ? "Queuing…" : `Ingest ${selected.size || ""}`.trim()}
        </Button>
      </div>
    </div>
  );
}

function formatDate(value: string | null): string {
  return value ? new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value)) : "—";
}

function formatBytes(bytes: number): string {
  if (bytes <= 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

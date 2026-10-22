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
      {/* Flex, not a grid keyed to the page: this pane can be narrow inside a
          wide page, and a grid column sized to the select squeezed the search. */}
      <div className="flex flex-wrap gap-2">
        <label className="relative min-w-0 flex-[2] basis-48">
          <span className="sr-only">Search source items</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-label-tertiary" strokeWidth={1.5} aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by name" className="field hit-target !pl-9" />
        </label>
        {/* `min-w-0` matters: a select's intrinsic width is its longest option,
            and a long media type would otherwise push it out of the pane. */}
        <label className="min-w-0 flex-1 basis-40">
          <span className="sr-only">Filter item type</span>
          <select value={type} onChange={(event) => setType(event.target.value)} className="field hit-target">
            <option value="all">All file types</option>
            {types.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
      </div>

      <p role="alert" className="text-footnote text-danger empty:hidden">
        {error ?? ""}
      </p>

      {visible.length === 0 ? (
        <p className="border-y border-separator py-4 text-footnote text-label-secondary">Nothing here matches that name and type. Your selection is kept.</p>
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
          { key: "type", header: "Type", render: (item) => <span className="block max-w-[14rem] truncate font-mono text-caption" title={item.content_type}>{item.content_type}</span> },
          { key: "size", header: "Size", render: (item) => <span className="font-mono text-footnote">{formatBytes(item.size_bytes)}</span> },
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

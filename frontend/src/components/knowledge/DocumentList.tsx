"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { FileText, MessageCircle, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import type { KnowledgeDocument } from "@/lib/knowledge/api";

export type DocumentListProps = {
  documents: KnowledgeDocument[];
  onDelete: (documentId: string) => Promise<void>;
};

type SortKey = "created" | "title" | "size" | "passages";

export function DocumentList({ documents, onDelete }: DocumentListProps) {
  const [pendingDelete, setPendingDelete] = useState<KnowledgeDocument | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [sort, setSort] = useState<SortKey>("created");

  const statuses = useMemo(() => [...new Set(documents.map((document) => document.status))].sort(), [documents]);
  const visible = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return documents
      .filter((document) => status === "all" || document.status === status)
      .filter((document) => normalized.length === 0 || document.title.toLocaleLowerCase().includes(normalized))
      .sort((left, right) => {
        if (sort === "title") return left.title.localeCompare(right.title);
        if (sort === "size") return right.byte_size - left.byte_size;
        if (sort === "passages") return right.chunk_count - left.chunk_count;
        return right.created_at.localeCompare(left.created_at);
      });
  }, [documents, query, sort, status]);

  if (documents.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        title="No documents yet"
        description="Upload a document above or connect a source, then ask about it in chat."
        headingLevel={3}
        action={<Link href="/sources" className="hit-target inline-flex items-center rounded-md px-4 font-semibold text-accent hover:bg-fill-tertiary">Connect a source</Link>}
      />
    );
  }

  return (
    <>
      <div className="flex flex-col gap-3">
        <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto_auto]">
          <label className="relative">
            <span className="sr-only">Search documents</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-label-tertiary" aria-hidden="true" />
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search documents" className="hit-target w-full rounded-md border border-separator bg-bg pl-10 pr-3 text-callout text-label" />
          </label>
          <label>
            <span className="sr-only">Filter document status</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)} className="hit-target rounded-md border border-separator bg-bg px-3 text-callout text-label">
              <option value="all">All statuses</option>
              {statuses.map((value) => <option key={value} value={value}>{statusLabel(value)}</option>)}
            </select>
          </label>
          <label>
            <span className="sr-only">Sort documents</span>
            <select value={sort} onChange={(event) => setSort(event.target.value as SortKey)} className="hit-target rounded-md border border-separator bg-bg px-3 text-callout text-label">
              <option value="created">Newest first</option>
              <option value="title">Title</option>
              <option value="size">Size</option>
              <option value="passages">Passages</option>
            </select>
          </label>
        </div>

        {visible.length === 0 ? (
          <EmptyState icon={Search} title="No documents match" description="Try a different title or status." headingLevel={3} />
        ) : (
          <div className="overflow-x-auto rounded-md border border-separator">
            <table className="w-full min-w-[44rem] border-collapse text-left text-footnote">
              <caption className="sr-only">Knowledge documents</caption>
              <thead>
                <tr className="bg-bg-tertiary">
                  <th className="border-b border-separator px-3 py-2 font-semibold text-label" scope="col">Document</th>
                  <th className="border-b border-separator px-3 py-2 font-semibold text-label" scope="col">Status</th>
                  <th className="border-b border-separator px-3 py-2 font-semibold text-label" scope="col">Passages</th>
                  <th className="border-b border-separator px-3 py-2 font-semibold text-label" scope="col">Size</th>
                  <th className="border-b border-separator px-3 py-2 font-semibold text-label" scope="col">Added</th>
                  <th className="border-b border-separator px-3 py-2"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((document) => (
                  <tr key={document.id}>
                    <td className="border-b border-separator px-3 py-3">
                      <span className="block max-w-64 truncate font-semibold text-label">{document.title}</span>
                      <span className="block text-caption text-label-secondary">{document.media_type}</span>
                    </td>
                    <td className="border-b border-separator px-3 py-3"><StatusChip document={document} /></td>
                    <td className="border-b border-separator px-3 py-3 text-label-secondary">{document.chunk_count} passages</td>
                    <td className="border-b border-separator px-3 py-3 text-label-secondary">{formatBytes(document.byte_size)}</td>
                    <td className="border-b border-separator px-3 py-3 text-label-secondary">{formatDate(document.created_at)}</td>
                    <td className="border-b border-separator px-2 py-1">
                      <div className="flex justify-end">
                        <Link href="/chat" aria-label={`Ask about ${document.title}`} className="hit-target inline-flex items-center justify-center rounded-md px-2 text-accent hover:bg-fill-tertiary">
                          <MessageCircle className="size-4" aria-hidden="true" />
                        </Link>
                        <Button rank="plain" aria-label={`Delete ${document.title}`} className="!px-2" onClick={() => setPendingDelete(document)}>
                          <Trash2 className="size-4" strokeWidth={1.5} aria-hidden="true" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <Dialog.Root open={pendingDelete !== null} onOpenChange={(open) => { if (!open) setPendingDelete(null); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay fixed inset-0 z-30 bg-label-quaternary" />
          <Dialog.Content className="dialog-content fixed left-1/2 top-1/2 z-40 w-[min(28rem,90vw)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-separator bg-bg p-6 shadow-lg">
            <Dialog.Title className="text-title-3 font-semibold tracking-title text-label">Delete {pendingDelete?.title}?</Dialog.Title>
            <Dialog.Description className="mt-2 text-callout leading-relaxed text-label-secondary">Its passages and embeddings go with it, and answers will stop citing it. This cannot be undone.</Dialog.Description>
            <div className="mt-6 flex justify-end gap-2">
              <Dialog.Close asChild><Button rank="plain">Cancel</Button></Dialog.Close>
              <Button rank="filled" className="!bg-danger" onClick={() => { const target = pendingDelete; setPendingDelete(null); if (target) void onDelete(target.id); }}>Delete</Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

function StatusChip({ document }: { document: KnowledgeDocument }) {
  const superseded = document.superseded_by !== null;
  const tone = superseded ? "text-warning" : document.status === "ready" ? "text-success" : document.status === "failed" ? "text-danger" : "text-info";
  return <span className={`inline-flex rounded-full bg-fill-tertiary px-2 py-1 font-semibold ${tone}`}>{superseded ? "Superseded" : statusLabel(document.status)}</span>;
}

function statusLabel(status: string): string { return status.charAt(0).toUpperCase() + status.slice(1).replaceAll("_", " "); }
function formatDate(value: string): string { return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value)); }
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

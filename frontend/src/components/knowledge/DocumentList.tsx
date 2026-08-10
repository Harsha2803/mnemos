"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { FileText, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { List, ListItem } from "@/components/ui/List";
import type { KnowledgeDocument } from "@/lib/knowledge/api";

export type DocumentListProps = {
  documents: KnowledgeDocument[];
  onDelete: (documentId: string) => Promise<void>;
};

export function DocumentList({ documents, onDelete }: DocumentListProps) {
  const [pendingDelete, setPendingDelete] = useState<KnowledgeDocument | null>(null);

  if (documents.length === 0) {
    return (
      <EmptyState
        icon={FileText}
        title="No documents yet"
        description="Upload one above, then ask about it in a chat."
        headingLevel={3}
      />
    );
  }

  return (
    <>
      <List label="Documents">
        {documents.map((document) => (
          <ListItem
            key={document.id}
            leading={<FileText className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />}
            trailing={
              <Button
                rank="plain"
                aria-label={`Delete ${document.title}`}
                onClick={() => setPendingDelete(document)}
              >
                <Trash2 className="size-4" strokeWidth={1.5} aria-hidden="true" />
              </Button>
            }
          >
            <span className="block truncate font-medium text-label">{document.title}</span>
            <span className="block text-footnote text-label-secondary">
              {document.chunk_count} passages · {formatBytes(document.byte_size)} ·{" "}
              {document.status}
            </span>
          </ListItem>
        ))}
      </List>

      {/* DesignSystem §4: a destructive confirmation names the specific thing
          being destroyed. "Delete document?" is not good enough. */}
      <Dialog.Root
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-30 bg-label-quaternary" />
          <Dialog.Content className="fixed left-1/2 top-1/2 z-40 w-[min(28rem,90vw)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-separator bg-bg p-6 shadow-lg">
            <Dialog.Title className="text-title-3 font-semibold tracking-title text-label">
              Delete {pendingDelete?.title}?
            </Dialog.Title>
            <Dialog.Description className="mt-2 text-callout leading-relaxed text-label-secondary">
              Its passages and embeddings go with it, and answers will stop citing it. This
              cannot be undone.
            </Dialog.Description>
            <div className="mt-6 flex justify-end gap-2">
              <Dialog.Close asChild>
                <Button rank="plain">Cancel</Button>
              </Dialog.Close>
              <Button
                rank="filled"
                className="!bg-danger"
                onClick={() => {
                  const target = pendingDelete;
                  setPendingDelete(null);
                  if (target) void onDelete(target.id);
                }}
              >
                Delete
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

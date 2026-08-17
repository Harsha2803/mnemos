"use client";

import { AlertCircle, CheckCircle2, Loader2, RotateCcw, Upload, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { Button } from "@/components/ui/Button";
import { uploadDocument } from "@/lib/knowledge/api";

export type UploadControlProps = { onUploaded: () => void };
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const MAX_UPLOAD_MB = MAX_UPLOAD_BYTES / (1024 * 1024);
type UploadState = "validating" | "uploading" | "done" | "failed";
type QueueItem = { id: string; file: File; state: UploadState; error: string | null };

export function UploadControl({ onUploaded }: UploadControlProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [dragging, setDragging] = useState(false);

  function update(id: string, values: Partial<QueueItem>): void {
    setQueue((current) => current.map((item) => item.id === id ? { ...item, ...values } : item));
  }

  async function uploadOne(item: QueueItem): Promise<boolean> {
    if (item.file.size > MAX_UPLOAD_BYTES) {
      update(item.id, { state: "failed", error: `larger than the ${MAX_UPLOAD_MB} MB limit` });
      return false;
    }
    update(item.id, { state: "uploading", error: null });
    try {
      await uploadDocument(item.file);
      update(item.id, { state: "done" });
      return true;
    } catch (cause) {
      update(item.id, { state: "failed", error: messageFor(cause) });
      return false;
    }
  }

  async function uploadAll(files: File[]): Promise<void> {
    const items = files.map((file) => ({ id: crypto.randomUUID(), file, state: "validating" as const, error: null }));
    setQueue(items);
    const results = await Promise.all(items.map(uploadOne));
    if (results.some(Boolean)) onUploaded();
  }

  async function retry(item: QueueItem): Promise<void> {
    update(item.id, { state: "validating", error: null });
    if (await uploadOne(item)) onUploaded();
  }

  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) void uploadAll(files);
  }

  const pending = queue.filter((item) => item.state === "validating" || item.state === "uploading").length;
  const done = queue.filter((item) => item.state === "done").length;
  const failed = queue.filter((item) => item.state === "failed").length;

  return (
    <div className="flex flex-col gap-3">
      <div onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop} className={["flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-6 text-center transition-colors", dragging ? "border-accent bg-accent-tint" : "border-separator bg-bg-secondary"].join(" ")}>
        <Upload className="size-6 text-label-tertiary" strokeWidth={1.5} aria-hidden="true" />
        <p className="text-callout text-label-secondary">Drop documents here, or choose them. Plain text, Markdown and PDF, up to {MAX_UPLOAD_MB} MB each.</p>
        <Button rank="tinted" onClick={() => inputRef.current?.click()}>Choose files</Button>
        <input ref={inputRef} type="file" multiple aria-label="Upload documents" accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf" className="sr-only" onChange={(event) => { const files = Array.from(event.target.files ?? []); if (files.length > 0) void uploadAll(files); event.target.value = ""; }} />
      </div>

      {queue.length > 0 && (
        <div className="rounded-lg border border-separator" role={pending > 0 ? "status" : undefined} aria-label={pending === 1 ? "Processing the document" : pending > 1 ? `Processing ${pending} documents` : "Upload summary"}>
          <div className="flex items-center justify-between border-b border-separator px-4 py-2 text-footnote text-label-secondary">
            <span>{pending > 0 ? `${pending} processing` : `${done} uploaded`}{failed > 0 ? ` · ${failed} failed` : ""}</span>
            {pending === 0 && <Button rank="plain" className="!px-2 text-footnote" onClick={() => setQueue([])}>Clear</Button>}
          </div>
          <ul className="divide-y divide-separator">
            {queue.map((item) => <QueueRow key={item.id} item={item} onRetry={() => void retry(item)} onRemove={() => setQueue((current) => current.filter((entry) => entry.id !== item.id))} />)}
          </ul>
        </div>
      )}
    </div>
  );
}

function QueueRow({ item, onRetry, onRemove }: { item: QueueItem; onRetry: () => void; onRemove: () => void }) {
  const active = item.state === "validating" || item.state === "uploading";
  return (
    <li className="flex items-center gap-3 px-4 py-3">
      {active ? <Loader2 className="size-4 shrink-0 animate-spin text-info" aria-hidden="true" /> : item.state === "done" ? <CheckCircle2 className="size-4 shrink-0 text-success" aria-hidden="true" /> : <AlertCircle className="size-4 shrink-0 text-danger" aria-hidden="true" />}
      <div className="min-w-0 flex-1">
        <span className="block truncate text-footnote font-semibold text-label">{item.file.name}</span>
        {item.state === "failed" ? (
          <span role="alert" className="block text-caption text-danger">{item.file.name}: {item.error ?? "Failed"}</span>
        ) : (
          <span className="block text-caption text-label-secondary">{formatBytes(item.file.size)} · {stateLabel(item.state)}</span>
        )}
      </div>
      {item.state === "failed" && <Button rank="plain" aria-label={`Retry ${item.file.name}`} className="!px-2" onClick={onRetry}><RotateCcw className="size-4" aria-hidden="true" /></Button>}
      {!active && <Button rank="plain" aria-label={`Remove ${item.file.name} from upload queue`} className="!px-2" onClick={onRemove}><X className="size-4" aria-hidden="true" /></Button>}
    </li>
  );
}

function stateLabel(state: UploadState): string { return state === "validating" ? "Validating" : state === "uploading" ? "Uploading and indexing" : state === "done" ? "Ready" : "Failed"; }
function messageFor(reason: unknown): string { return reason instanceof Error ? reason.message : "could not upload this document"; }
function formatBytes(bytes: number): string { if (bytes < 1024) return `${bytes} B`; if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`; return `${(bytes / (1024 * 1024)).toFixed(1)} MB`; }

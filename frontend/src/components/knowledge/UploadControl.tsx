"use client";

import { Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { uploadDocument } from "@/lib/knowledge/api";

export type UploadControlProps = {
  onUploaded: () => void;
};

/**
 * Mirrors the backend's own ceiling (`Settings.max_upload_bytes`,
 * `core/config.py`) — checked here too so an oversized file is refused the
 * moment it is chosen, not after it has spent a minute going up over a slow
 * connection only to be rejected on arrival.
 */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const MAX_UPLOAD_MB = MAX_UPLOAD_BYTES / (1024 * 1024);

/**
 * Drag-and-drop or a file picker, either one or several at once, with a
 * **skeleton** while the batch is extracted, chunked and embedded — never a
 * spinner (DesignSystem §4), because the shape of what is coming is rows in
 * the library and the skeleton says so.
 *
 * Every file in a drop or a selection is sent as its own request — how many
 * of those the API actually runs at once is however many worker processes
 * `docker-compose.yml` gives the `api` service, not a limit this control
 * imposes — and one bad file (too large, an unsupported type) does not stop
 * the rest: `Promise.allSettled` lets every other upload finish, and each
 * failure is named against the file it came from.
 */
export function UploadControl({ onUploaded }: UploadControlProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [pendingCount, setPendingCount] = useState(0);
  const [errors, setErrors] = useState<string[]>([]);
  const [dragging, setDragging] = useState(false);

  async function uploadOne(file: File): Promise<void> {
    if (file.size > MAX_UPLOAD_BYTES) {
      throw new Error(`larger than the ${MAX_UPLOAD_MB} MB limit`);
    }
    await uploadDocument(file);
  }

  async function uploadAll(files: File[]): Promise<void> {
    setErrors([]);
    setPendingCount(files.length);
    const results = await Promise.allSettled(files.map(uploadOne));
    setPendingCount(0);

    const failures = results
      .map((result, index) => (result.status === "rejected" ? [result, files[index]] : null))
      .filter((entry): entry is [PromiseRejectedResult, File] => entry !== null)
      .map(([result, file]) => `${file.name}: ${messageFor(result.reason)}`);
    setErrors(failures);

    if (failures.length < files.length) onUploaded();
  }

  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragging(false);
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) void uploadAll(files);
  }

  if (pendingCount > 0) {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-separator p-6">
        <Skeleton
          label={
            pendingCount === 1 ? "Processing the document" : `Processing ${pendingCount} documents`
          }
          className="h-4 w-48"
        />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-5/6" />
        <Skeleton className="h-3 w-2/3" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={[
          "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-8 text-center",
          "transition-colors duration-150 ease-standard",
          dragging ? "border-accent bg-accent-tint" : "border-separator bg-bg-secondary",
        ].join(" ")}
      >
        <Upload className="size-6 text-label-tertiary" strokeWidth={1.5} aria-hidden="true" />
        <p className="text-callout text-label-secondary">
          Drop documents here, or choose them. Plain text, Markdown and PDF, up to{" "}
          {MAX_UPLOAD_MB} MB each.
        </p>
        <Button rank="tinted" onClick={() => inputRef.current?.click()}>
          Choose files
        </Button>
        <input
          ref={inputRef}
          type="file"
          multiple
          aria-label="Upload documents"
          accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf"
          className="sr-only"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            if (files.length > 0) void uploadAll(files);
            event.target.value = "";
          }}
        />
      </div>
      {errors.length > 0 && (
        <ul className="flex flex-col gap-1">
          {errors.map((message) => (
            <li key={message} role="alert" className="text-footnote text-danger">
              {message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function messageFor(reason: unknown): string {
  return reason instanceof Error ? reason.message : "could not upload this document";
}

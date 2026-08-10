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
 * Drag-and-drop or a file picker, with a **skeleton** while the document is
 * extracted, chunked and embedded — never a spinner (DesignSystem §4), because
 * the shape of what is coming is a row in the library and the skeleton says so.
 *
 * A failure names what went wrong, using the API's own message: "unsupported
 * media type" and "too large" are both things the user can act on, and
 * `ValidationError` is deliberately the one error whose details cross the
 * boundary.
 */
export function UploadControl({ onUploaded }: UploadControlProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  async function upload(file: File): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await uploadDocument(file);
      onUploaded();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "could not upload this document");
    } finally {
      setBusy(false);
    }
  }

  function onDrop(event: DragEvent<HTMLDivElement>): void {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files.item(0);
    if (file !== null) void upload(file);
  }

  if (busy) {
    return (
      <div className="flex flex-col gap-3 rounded-lg border border-separator p-6">
        <Skeleton label="Processing the document" className="h-4 w-48" />
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
          Drop a document here, or choose one. Plain text, Markdown and PDF.
        </p>
        <Button rank="tinted" onClick={() => inputRef.current?.click()}>
          Choose a file
        </Button>
        <input
          ref={inputRef}
          type="file"
          aria-label="Upload a document"
          accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf"
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.item(0);
            if (file) void upload(file);
            event.target.value = "";
          }}
        />
      </div>
      {error !== null && (
        <p role="alert" className="text-footnote text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

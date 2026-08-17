"use client";

import { ChevronLeft, ChevronRight, FileSearch, Layers } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import type { Nl2SqlResult } from "@/lib/chat/stream";
import { useInspectorSelection, type InspectorMessage } from "@/lib/inspector/SelectionProvider";
import type { Citation } from "@/lib/knowledge/api";

export function InspectorContent() {
  const { selection, select } = useInspectorSelection();

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center border-b border-separator px-4">
        <h2 className="text-subheadline font-semibold text-label">Context</h2>
      </div>

      {selection === null ? (
        <div className="flex flex-1 items-center justify-center">
          <EmptyState
            icon={Layers}
            title="No message selected"
            description="Select an answer or citation to review its evidence. SQL answers also expose their query safety and execution details here."
            headingLevel={3}
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <nav aria-label="Inspector sections" className="flex shrink-0 gap-1 border-b border-separator p-2">
            <InspectorTab
              label="Evidence"
              active={selection.kind === "message" || selection.kind === "citation"}
              onClick={() => select({ kind: "message", message: selection.message })}
            />
            {selection.message.nl2sql && (
              <InspectorTab
                label="SQL"
                active={selection.kind === "sql"}
                onClick={() =>
                  select({
                    kind: "sql",
                    message: selection.message,
                    result: selection.message.nl2sql as Nl2SqlResult,
                  })
                }
              />
            )}
            <InspectorTab
              label="Bundle"
              active={selection.kind === "bundle"}
              onClick={() => select({ kind: "bundle", message: selection.message })}
            />
          </nav>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {selection.kind === "citation" && (
              <CitationView message={selection.message} citation={selection.citation} />
            )}
            {selection.kind === "message" && <EvidenceView message={selection.message} />}
            {selection.kind === "sql" && <SqlView result={selection.result} />}
            {selection.kind === "bundle" && <BundleView message={selection.message} />}
          </div>
        </div>
      )}
    </div>
  );
}

function InspectorTab({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-current={active ? "page" : undefined}
      onClick={onClick}
      className="hit-target flex-1 rounded-md px-2 text-footnote font-semibold text-label-secondary hover:bg-fill-tertiary aria-[current=page]:bg-accent-tint aria-[current=page]:text-accent"
    >
      {label}
    </button>
  );
}

function EvidenceView({ message }: { message: InspectorMessage }) {
  const { select } = useInspectorSelection();
  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-footnote font-semibold uppercase tracking-wide text-label-secondary">Answer evidence</p>
        <p className="mt-1 text-footnote text-label-secondary">
          {message.citations.length === 0
            ? "This answer did not return document citations."
            : `${message.citations.length} source${message.citations.length === 1 ? "" : "s"} supported this answer.`}
        </p>
      </div>
      {message.citations.map((citation) => (
        <button
          key={citation.id}
          type="button"
          onClick={() => select({ kind: "citation", message, citation })}
          className="hit-target flex flex-col items-start rounded-md border border-separator bg-bg-secondary p-3 text-left hover:bg-fill-tertiary"
        >
          <span className="font-semibold text-label">Source [{citation.marker}]</span>
          <span className="mt-1 line-clamp-3 text-footnote leading-relaxed text-label-secondary">
            {citation.quoted_text}
          </span>
          <span className="mt-2 text-caption text-label-tertiary">{citationMetadata(citation)}</span>
        </button>
      ))}
    </div>
  );
}

function CitationView({ message, citation }: { message: InspectorMessage; citation: Citation }) {
  const { select } = useInspectorSelection();
  const citations = [...message.citations].sort((a, b) => a.marker - b.marker);
  const index = citations.findIndex((item) => item.id === citation.id);
  const previous = index > 0 ? citations[index - 1] : undefined;
  const next = index >= 0 && index < citations.length - 1 ? citations[index + 1] : undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <div>
          <span className="text-footnote font-semibold text-label-secondary">Source [{citation.marker}]</span>
          <p className="text-callout font-semibold text-label">
            {citation.page_number !== null ? `Page ${citation.page_number}` : "Document passage"}
          </p>
        </div>
        <div className="flex gap-1">
          <Button rank="plain" aria-label="Previous citation" disabled={!previous} className="!px-2" onClick={() => previous && select({ kind: "citation", message, citation: previous })}>
            <ChevronLeft className="size-4" aria-hidden="true" />
          </Button>
          <Button rank="plain" aria-label="Next citation" disabled={!next} className="!px-2" onClick={() => next && select({ kind: "citation", message, citation: next })}>
            <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>
      <p className="text-footnote text-label-secondary">{citationMetadata(citation)}</p>
      <blockquote className="whitespace-pre-wrap rounded-lg border-l-2 border-accent bg-bg-tertiary p-3 text-footnote leading-relaxed text-label">
        {citation.quoted_text}
      </blockquote>
      <Button rank="tinted" onClick={() => select({ kind: "message", message })}>
        <FileSearch className="size-4" aria-hidden="true" />
        View all evidence
      </Button>
    </div>
  );
}

function SqlView({ result }: { result: Nl2SqlResult }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 text-footnote">
        <Metric label="Verdict" value={result.verdict === "allowed" ? "Allowed" : "Refused"} />
        <Metric label="Attempt" value={String(result.attempt)} />
        <Metric label="Duration" value={result.duration_ms === null ? "—" : `${result.duration_ms} ms`} />
        <Metric label="Rows" value={result.row_count === null ? "—" : String(result.row_count)} />
      </div>
      <div>
        <p className="text-footnote font-semibold text-label-secondary">Authorized tables</p>
        <p className="mt-1 text-footnote text-label">{result.authorized_tables.join(", ") || "None"}</p>
      </div>
      {result.denied_tables.length > 0 && (
        <div>
          <p className="text-footnote font-semibold text-danger">Denied tables</p>
          <p className="mt-1 text-footnote text-label">{result.denied_tables.join(", ")}</p>
        </div>
      )}
      <pre className="overflow-x-auto rounded-md bg-bg-tertiary p-3 text-footnote text-label">
        <code className="font-mono">{result.sql}</code>
      </pre>
    </div>
  );
}

function BundleView({ message }: { message: InspectorMessage }) {
  return (
    <div className="flex flex-col items-center gap-3 py-8 text-center">
      <Layers className="size-8 text-info" strokeWidth={1.5} aria-hidden="true" />
      <h3 className="text-callout font-semibold text-label">Context bundle summary</h3>
      <p className="text-footnote leading-relaxed text-label-secondary">
        {message.citations.length} admitted evidence item{message.citations.length === 1 ? "" : "s"} can be reviewed now. Token budgets, excluded items, retrieval operators, and degradation events require the context-layer contract.
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-bg-tertiary p-3">
      <span className="block text-caption text-label-secondary">{label}</span>
      <span className="mt-1 block font-semibold text-label">{value}</span>
    </div>
  );
}

function citationMetadata(citation: Citation): string {
  const values: string[] = [];
  if (citation.start_char !== null && citation.end_char !== null) values.push(`Characters ${citation.start_char}–${citation.end_char}`);
  if (citation.score !== null) values.push(`relevance ${citation.score.toFixed(2)}`);
  return values.join(" · ") || "Passage location unavailable";
}

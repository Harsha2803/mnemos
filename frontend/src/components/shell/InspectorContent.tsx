"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Copy, Layers } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { RelativeTime } from "@/components/ui/RelativeTime";
import { RevisionMark } from "@/components/ui/RevisionMark";
import { Skeleton } from "@/components/ui/Skeleton";
import type { Nl2SqlResult } from "@/lib/chat/stream";
import {
  contextBundleQueryKey,
  fetchContextBundle,
  type ContextBundle,
} from "@/lib/context/api";
import { useInspectorSelection, type InspectorMessage } from "@/lib/inspector/SelectionProvider";
import { fetchDocuments, KNOWLEDGE_QUERY_KEY, type Citation } from "@/lib/knowledge/api";

export type InspectorContentProps = {
  headerAction?: ReactNode;
  /**
   * Move focus to the panel's heading when it mounts — for a panel a person
   * just asked to open (the rail), so a keyboard user lands inside it rather
   * than on a control that no longer exists.
   */
  focusOnMount?: boolean;
};

export function InspectorContent({ headerAction, focusOnMount = false }: InspectorContentProps = {}) {
  const { selection, select } = useInspectorSelection();
  const heading = useRef<HTMLHeadingElement>(null);
  const titles = useDocumentTitles(selection !== null);

  useEffect(() => {
    if (focusOnMount) heading.current?.focus();
    // Only on mount: a later re-render must not pull focus back here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-separator pl-4 pr-2">
        <h2
          ref={heading}
          tabIndex={-1}
          className="font-mono text-caption uppercase tracking-caps text-label-secondary focus-visible:outline-none"
        >
          Context
        </h2>
        <div className="ml-auto">{headerAction}</div>
      </div>

      {selection === null ? (
        <div className="flex flex-1 flex-col gap-3 p-5">
          <EmptyState
            icon={Layers}
            title="No message selected"
            description="Choose an answer, or one of its source numerals, to read the evidence behind it: the passages it quoted, what the context compiler admitted and left out, and for data answers, the SQL and its guard."
            headingLevel={3}
            className="!items-start !px-0 !py-4 !text-left"
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col">
          <nav aria-label="Inspector sections" className="flex shrink-0 gap-4 border-b border-separator px-4">
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

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
            {selection.kind === "citation" && (
              <CitationView message={selection.message} citation={selection.citation} titles={titles} />
            )}
            {selection.kind === "message" && <EvidenceView message={selection.message} titles={titles} />}
            {selection.kind === "sql" && <SqlView result={selection.result} />}
            {selection.kind === "bundle" && <BundleView message={selection.message} titles={titles} />}
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
      className={[
        "hit-target relative px-0 text-footnote font-medium text-label-secondary transition-colors duration-150 ease-standard",
        "hover:text-label aria-[current=page]:font-semibold aria-[current=page]:text-label",
        "after:absolute after:inset-x-0 after:-bottom-px after:h-0.5 after:bg-transparent aria-[current=page]:after:bg-rubric",
      ].join(" ")}
    >
      {label}
    </button>
  );
}

/** Document titles by id, from the cached library list. */
function useDocumentTitles(enabled: boolean): ReadonlyMap<string, string> {
  const documents = useQuery({
    queryKey: KNOWLEDGE_QUERY_KEY,
    queryFn: ({ signal }) => fetchDocuments(signal),
    enabled,
  });
  return useMemo(
    () => new Map((Array.isArray(documents.data) ? documents.data : []).map((d) => [d.id, d.title])),
    [documents.data],
  );
}

function titleOf(documentId: string | null, titles: ReadonlyMap<string, string>): string {
  return (documentId === null ? undefined : titles.get(documentId)) ?? "Document passage";
}

/** A small mono caps label naming the field or section below it. */
function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <p className={`font-mono text-caption uppercase tracking-caps text-label-secondary ${className}`.trim()}>
      {children}
    </p>
  );
}

function EvidenceView({ message, titles }: { message: InspectorMessage; titles: ReadonlyMap<string, string> }) {
  const { select } = useInspectorSelection();
  const citations = [...message.citations].sort((a, b) => a.marker - b.marker);
  const documents = new Set(citations.map((citation) => citation.document_id));

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Label>Evidence for this answer</Label>
        <p className="mt-1 text-footnote text-label-secondary">
          {citations.length === 0
            ? message.nl2sql !== undefined
              ? "This answer came from data, not documents. Its query is under SQL."
              : "This answer cites no passages. Its compiled context is under Bundle."
            : `${citations.length} passage${citations.length === 1 ? "" : "s"} from ${documents.size} document${documents.size === 1 ? "" : "s"}.`}
        </p>
      </div>
      {citations.length > 0 && (
        <ol className="flex flex-col border-t border-separator">
          {citations.map((citation) => (
            <li key={citation.id} className="border-b border-separator">
              <button
                type="button"
                onClick={() => select({ kind: "citation", message, citation })}
                className="hit-target group flex w-full flex-col items-start gap-1 py-3 text-left"
              >
                <span className="flex w-full items-baseline gap-2 text-footnote">
                  <span className="font-semibold text-rubric">{citation.marker}</span>
                  <span className="min-w-0 flex-1 truncate font-semibold text-label group-hover:underline">
                    {titleOf(citation.document_id, titles)}
                  </span>
                  {citation.page_number !== null && (
                    <span className="shrink-0 font-mono text-caption text-label-secondary">p.{citation.page_number}</span>
                  )}
                </span>
                <span className="line-clamp-3 font-serif text-footnote leading-relaxed text-label-secondary">
                  {citation.quoted_text}
                </span>
                <span className="font-mono text-caption text-label-secondary">{citationMetadata(citation)}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function CitationView({
  message,
  citation,
  titles,
}: {
  message: InspectorMessage;
  citation: Citation;
  titles: ReadonlyMap<string, string>;
}) {
  const { select } = useInspectorSelection();
  const citations = [...message.citations].sort((a, b) => a.marker - b.marker);
  const index = citations.findIndex((item) => item.id === citation.id);
  const previous = index > 0 ? citations[index - 1] : undefined;
  const next = index >= 0 && index < citations.length - 1 ? citations[index + 1] : undefined;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <Label>
          Source {citation.marker}
          {citations.length > 1 ? ` of ${citations.length}` : ""}
        </Label>
        <div className="-mr-2 flex">
          <Button
            rank="plain"
            aria-label="Previous citation"
            disabled={!previous}
            className="!px-0"
            onClick={() => previous && select({ kind: "citation", message, citation: previous })}
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
          </Button>
          <Button
            rank="plain"
            aria-label="Next citation"
            disabled={!next}
            className="!px-0"
            onClick={() => next && select({ kind: "citation", message, citation: next })}
          >
            <ChevronRight className="size-4" aria-hidden="true" />
          </Button>
        </div>
      </div>
      <div>
        <h3 className="font-serif text-title-3 font-semibold leading-tight tracking-title text-label">
          {titleOf(citation.document_id, titles)}
        </h3>
        <p className="mt-1 flex flex-wrap gap-x-2 text-footnote text-label-secondary">
          {citation.page_number !== null && <span>Page {citation.page_number}</span>}
          <span className="font-mono text-caption">{citationMetadata(citation)}</span>
        </p>
      </div>
      {/* The whole retrieved passage — the text the model was given, not an
          excerpt of it — set as reading text with the rubric rule that marks
          provenance everywhere else. */}
      <blockquote className="whitespace-pre-wrap border-l-2 border-rubric pl-4 font-serif text-callout leading-relaxed text-label">
        {citation.quoted_text}
      </blockquote>
      <div>
        <Button rank="plain" className="!px-0" onClick={() => select({ kind: "message", message })}>
          All evidence for this answer
        </Button>
      </div>
    </div>
  );
}

function SqlView({ result }: { result: Nl2SqlResult }) {
  const [copied, setCopied] = useState(false);
  const refused = result.verdict !== "allowed";

  async function copySql(): Promise<void> {
    await navigator.clipboard.writeText(result.sql);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="flex flex-col gap-5">
      <div>
        <Label>Read-only guard</Label>
        <p className={`mt-1 text-callout font-semibold ${refused ? "text-danger" : "text-success"}`}>
          {refused ? "Refused — the query did not run" : result.executed ? "Allowed and run" : "Allowed, but the database could not run it"}
        </p>
      </div>
      <dl className="grid grid-cols-3 gap-3 border-y border-separator py-3">
        <Metric label="Attempt" value={String(result.attempt)} />
        <Metric label="Duration" value={result.duration_ms === null ? "—" : `${result.duration_ms} ms`} />
        <Metric label="Rows" value={result.row_count === null ? "—" : String(result.row_count)} />
      </dl>
      <div className="flex flex-col gap-1">
        <Label>Tables read</Label>
        <p className="font-mono text-footnote text-label">{result.authorized_tables.join(", ") || "None"}</p>
      </div>
      {result.denied_tables.length > 0 && (
        <div className="flex flex-col gap-1">
          <Label className="!text-danger">Tables denied</Label>
          <p className="font-mono text-footnote text-label">{result.denied_tables.join(", ")}</p>
        </div>
      )}
      <div className="flex flex-col gap-1">
        <div className="flex items-center justify-between">
          <Label>Generated SQL</Label>
          <Button rank="plain" aria-label="Copy SQL" className="-mr-2 !px-2 text-footnote" onClick={() => void copySql()}>
            {copied ? <Check className="size-3.5" aria-hidden="true" /> : <Copy className="size-3.5" aria-hidden="true" />}
            {copied ? "Copied" : "Copy"}
          </Button>
        </div>
        <pre className="overflow-x-auto rounded-sm bg-bg-tertiary p-3 font-mono text-footnote leading-relaxed text-label">
          <code>{result.sql}</code>
        </pre>
      </div>
    </div>
  );
}

function BundleView({ message, titles }: { message: InspectorMessage; titles: ReadonlyMap<string, string> }) {
  const bundle = useQuery({
    queryKey: contextBundleQueryKey(message.id),
    queryFn: ({ signal }) => fetchContextBundle(message.id, signal),
  });

  if (bundle.isPending) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton label="Loading context bundle" className="h-16 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  if (bundle.isError) {
    return (
      <EmptyState
        icon={Layers}
        title="The bundle could not be loaded"
        description={`${bundle.error.message}. The answer itself is unaffected; try again in a moment.`}
        headingLevel={3}
        action={
          <Button rank="tinted" onClick={() => void bundle.refetch()}>
            Try again
          </Button>
        }
      />
    );
  }

  if (bundle.data === null) {
    return (
      <EmptyState
        icon={Layers}
        title="No persisted bundle"
        description="This answer predates governed context, or its flow did not compile a context artifact."
        headingLevel={3}
      />
    );
  }

  return <PersistedBundle bundle={bundle.data} titles={titles} />;
}

function PersistedBundle({ bundle, titles }: { bundle: ContextBundle; titles: ReadonlyMap<string, string> }) {
  const percent = Math.min(100, Math.round((bundle.tokens_consumed / bundle.token_budget) * 100));
  const refine = objectFrom(bundle.explain.refine);
  const conflicts = numberFrom(refine.conflicts_demoted);
  const conflictDetails = arrayFrom(refine.conflicts);

  return (
    <div className="flex flex-col gap-7">
      <section aria-labelledby="budget-heading" className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between gap-2">
          <h3 id="budget-heading" className="text-callout font-semibold text-label">Hard token budget</h3>
          <span className="font-mono text-footnote text-label">{percent}%</span>
        </div>
        <div
          className="h-1 overflow-hidden rounded-full bg-fill"
          role="progressbar"
          aria-label="Context token spend"
          aria-valuemin={0}
          aria-valuemax={bundle.token_budget}
          aria-valuenow={bundle.tokens_consumed}
        >
          <div className="h-full bg-accent" style={{ width: `${percent}%` }} />
        </div>
        <p className="font-mono text-caption text-label-secondary">
          {bundle.tokens_consumed.toLocaleString()} of {bundle.token_budget.toLocaleString()} tokens ·{" "}
          {(bundle.token_budget - bundle.tokens_consumed).toLocaleString()} headroom
        </p>
      </section>

      <BundleSection title={`Admitted · ${bundle.admitted.length}`}>
        {bundle.admitted.length === 0 ? (
          <p className="text-footnote text-label-secondary">No candidate survived the budget and policy gates.</p>
        ) : (
          <ol className="flex flex-col border-t border-separator">
            {bundle.admitted.map((item, index) => (
              <li key={item.id} className="flex flex-col gap-1 border-b border-separator py-3">
                <div className="flex items-baseline gap-2 text-footnote">
                  <span className="font-mono text-caption text-label-secondary">{index + 1}</span>
                  <span className="min-w-0 flex-1 truncate font-semibold text-label" title={item.document_title ?? item.source_ref}>
                    {item.document_title ?? item.source_ref}
                  </span>
                  <span className="shrink-0 font-mono text-caption text-label">{item.tokens} tok</span>
                </div>
                <p className="line-clamp-4 whitespace-pre-wrap font-serif text-footnote leading-relaxed text-label-secondary">
                  {item.text}
                </p>
                <p className="font-mono text-caption text-label-secondary">
                  {item.section} · {item.operator} · trust {item.trust_tier} · utility {item.utility.toFixed(3)} · density{" "}
                  {item.density.toFixed(4)}
                </p>
                <p className="font-mono text-caption text-label-secondary">ACL {item.acl_rule}</p>
              </li>
            ))}
          </ol>
        )}
      </BundleSection>

      <BundleSection title={`Excluded · ${bundle.rejections.length}`}>
        {bundle.rejections.length === 0 ? (
          <p className="text-footnote text-label-secondary">Every candidate passed.</p>
        ) : (
          <ul className="flex flex-col border-t border-separator">
            {bundle.rejections.map((item) => (
              <li key={`${item.key}-${item.reason}`} className="flex flex-col gap-1 border-b border-separator py-3">
                <div className="flex items-baseline justify-between gap-2 text-footnote">
                  <span className="min-w-0 truncate text-label-secondary line-through decoration-rubric" title={item.source_ref}>
                    {item.source_ref}
                  </span>
                  <span className="shrink-0 font-mono text-caption text-label-secondary">{item.tokens} tok</span>
                </div>
                <p className="font-mono text-caption uppercase tracking-caps text-warning">{humanize(item.reason)}</p>
                {item.detail && <p className="text-footnote text-label-secondary">{item.detail}</p>}
              </li>
            ))}
          </ul>
        )}
      </BundleSection>

      <BundleSection title="Decisions and lineage">
        <dl className="grid grid-cols-2 gap-x-3 gap-y-3">
          <Metric label="Flow" value={bundle.flow} />
          <Metric label="Conflicts demoted" value={String(conflicts)} />
          <Metric label="Digest" value={bundle.digest.slice(0, 12)} mono />
          <div>
            <dt className="font-mono text-caption uppercase tracking-caps text-label-secondary">Compiled</dt>
            <dd className="mt-0.5 text-footnote text-label">
              <RelativeTime value={bundle.created_at} form="long" />
            </dd>
          </div>
        </dl>
        {(bundle.lineage.length > 0 || conflictDetails.length > 0) && (
          <ul className="flex flex-col gap-3 text-footnote">
            {bundle.lineage.map((edge) => (
              <li key={`${edge.source_id}-${edge.target_id}-${edge.kind}`}>
                {edge.kind === "supersedes" ? (
                  <RevisionMark
                    previous={nameOf(edge.target_id, titles)}
                    current={nameOf(edge.source_id, titles)}
                    note={edge.rationale ?? undefined}
                  />
                ) : (
                  <span className="text-label-secondary">
                    <span className="font-semibold text-label">{humanize(edge.kind)}</span>: {nameOf(edge.source_id, titles)} →{" "}
                    {nameOf(edge.target_id, titles)}
                    {edge.rationale ? ` · ${edge.rationale}` : ""}
                  </span>
                )}
              </li>
            ))}
            {conflictDetails.map((value, index) => {
              const detail = objectFrom(value);
              return (
                <li key={index}>
                  <RevisionMark
                    previous={String(detail.candidate ?? "candidate")}
                    current={String(detail.preferred_source ?? "newer claim")}
                    note="demoted in a conflict"
                  />
                </li>
              );
            })}
          </ul>
        )}
      </BundleSection>

      <details className="group border-t border-separator pt-1">
        <summary className="hit-target flex cursor-pointer items-center justify-between text-footnote font-semibold text-label">
          Compiled prompt
          <ChevronRight className="size-4 text-label-secondary transition-transform group-open:rotate-90" aria-hidden="true" />
        </summary>
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-sm bg-bg-tertiary p-3 font-mono text-caption leading-relaxed text-label-secondary">
          <code>{bundle.compiled_prompt}</code>
        </pre>
      </details>
    </div>
  );
}

function BundleSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-callout font-semibold text-label">{title}</h3>
      {children}
    </section>
  );
}

function Metric({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <dt className="font-mono text-caption uppercase tracking-caps text-label-secondary">{label}</dt>
      <dd className={`mt-0.5 truncate text-footnote text-label ${mono ? "font-mono" : "font-semibold"}`} title={value}>
        {value}
      </dd>
    </div>
  );
}

/** A lineage endpoint by name where the library knows it, else a short id. */
function nameOf(id: string, titles: ReadonlyMap<string, string>): string {
  return titles.get(id) ?? id.slice(0, 8);
}

function numberFrom(value: unknown): number {
  return typeof value === "number" ? value : 0;
}

function objectFrom(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

function arrayFrom(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function humanize(value: string): string {
  return value.replaceAll("_", " ");
}

function citationMetadata(citation: Citation): string {
  const values: string[] = [];
  if (citation.start_char !== null && citation.end_char !== null) values.push(`Characters ${citation.start_char}–${citation.end_char}`);
  if (citation.score !== null) values.push(`relevance ${citation.score.toFixed(2)}`);
  return values.join(" · ") || "Passage location unavailable";
}

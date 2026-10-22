"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, RotateCcw, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { RevisionMark } from "@/components/ui/RevisionMark";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader, SectionHeading } from "@/components/ui/PageHeader";
import { RelativeTime } from "@/components/ui/RelativeTime";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  createMemory,
  fetchMemoryHistory,
  MEMORY_QUERY_KEY,
  retractMemory,
  supersedeMemory,
  type MemoryClaim,
  type MemoryFilters,
  type MemoryHistory,
  type MemoryWrite,
} from "@/lib/memory/api";

const INPUT = "field hit-target";
const TEXTAREA = "field hit-target min-h-24";

type Draft = {
  subjectKind: string;
  subjectRef: string;
  subjectName: string;
  predicate: string;
  objectText: string;
  kind: MemoryWrite["kind"];
  validFrom: string;
  validTo: string;
  confidence: string;
};

const EMPTY_DRAFT: Draft = {
  subjectKind: "person",
  subjectRef: "",
  subjectName: "",
  predicate: "",
  objectText: "",
  kind: "fact",
  validFrom: "",
  validTo: "",
  confidence: "1",
};

export default function MemoryPage() {
  const queryClient = useQueryClient();
  const [filters, setFilters] = useState<MemoryFilters>({ includeRetracted: true });
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [superseding, setSuperseding] = useState<MemoryClaim | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const history = useQuery({
    queryKey: [...MEMORY_QUERY_KEY, filters],
    queryFn: ({ signal }) => fetchMemoryHistory(filters, signal),
  });
  const save = useMutation({
    mutationFn: async () => {
      const input = toWrite(draft);
      return superseding ? supersedeMemory(superseding.id, input) : createMemory(input);
    },
    onSuccess: (claim) => {
      setNotice(superseding ? `Superseded with ${claim.subject.display_name} · ${claim.predicate}.` : `Saved ${claim.subject.display_name} · ${claim.predicate}.`);
      setDraft(EMPTY_DRAFT);
      setSuperseding(null);
      void queryClient.invalidateQueries({ queryKey: MEMORY_QUERY_KEY });
    },
  });
  const retract = useMutation({
    mutationFn: retractMemory,
    onSuccess: () => {
      setNotice("Claim retracted. Its belief-time history remains available.");
      void queryClient.invalidateQueries({ queryKey: MEMORY_QUERY_KEY });
    },
  });

  function beginSupersede(claim: MemoryClaim) {
    setSuperseding(claim);
    setDraft({
      subjectKind: claim.subject.kind,
      subjectRef: claim.subject.external_ref,
      subjectName: claim.subject.display_name,
      predicate: claim.predicate,
      objectText: "",
      kind: claim.kind as MemoryWrite["kind"],
      validFrom: toLocalDateTime(claim.valid_from),
      validTo: claim.valid_to.startsWith("9999-") ? "" : toLocalDateTime(claim.valid_to),
      confidence: String(claim.confidence),
    });
    globalThis.scrollTo?.({ top: 0, behavior: "smooth" });
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="Memory"
        description="Durable claims Mnemos can use in answers. Nothing is overwritten: a new fact about the same subject supersedes the old one, and both stay on record on two clocks, when it was true and when Mnemos believed it."
      />

      <section aria-labelledby="write-heading" className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <SectionHeading id="write-heading">{superseding ? "Supersede claim" : "Record a claim"}</SectionHeading>
          {superseding && <Button rank="plain" onClick={() => { setSuperseding(null); setDraft(EMPTY_DRAFT); }}>Cancel</Button>}
        </div>
        {superseding && (
          <p className="border-l-2 border-rubric pl-3 text-footnote text-label">
            Replacing <span className="font-semibold">{superseding.subject.display_name} · {superseding.predicate}</span>: “{superseding.object_text}”. The old claim stays in history; this creates its replacement.
          </p>
        )}
        <form className="grid grid-cols-1 gap-4 rounded-md border border-separator p-4 @xl/content:grid-cols-2" onSubmit={(event) => { event.preventDefault(); setNotice(null); save.mutate(); }}>
          <Field label="Subject type"><input required className={INPUT} value={draft.subjectKind} onChange={(event) => setDraft({ ...draft, subjectKind: event.target.value })} /></Field>
          <Field label="Subject reference"><input required className={INPUT} placeholder="employee:ada" value={draft.subjectRef} onChange={(event) => setDraft({ ...draft, subjectRef: event.target.value })} /></Field>
          <Field label="Subject name"><input required className={INPUT} placeholder="Ada Lovelace" value={draft.subjectName} onChange={(event) => setDraft({ ...draft, subjectName: event.target.value })} /></Field>
          <Field label="Predicate"><input required className={INPUT} placeholder="prefers_editor" value={draft.predicate} onChange={(event) => setDraft({ ...draft, predicate: event.target.value })} /></Field>
          <Field label="Claim kind"><select className={INPUT} value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as MemoryWrite["kind"] })}><option value="fact">Fact</option><option value="preference">Preference</option><option value="decision">Decision</option><option value="observation">Observation</option></select></Field>
          <Field label="Confidence"><input required type="number" min="0" max="1" step="0.01" className={INPUT} value={draft.confidence} onChange={(event) => setDraft({ ...draft, confidence: event.target.value })} /></Field>
          <Field label="Valid from"><input type="datetime-local" className={INPUT} value={draft.validFrom} onChange={(event) => setDraft({ ...draft, validFrom: event.target.value })} /></Field>
          <Field label="Valid to"><input type="datetime-local" className={INPUT} value={draft.validTo} onChange={(event) => setDraft({ ...draft, validTo: event.target.value })} /></Field>
          <Field label="Claim" className="@xl/content:col-span-2"><textarea required className={TEXTAREA} value={draft.objectText} onChange={(event) => setDraft({ ...draft, objectText: event.target.value })} /></Field>
          <div className="flex flex-wrap items-center gap-3 @xl/content:col-span-2">
            <Button rank="filled" type="submit" disabled={save.isPending}>{superseding ? "Create replacement" : "Save claim"}</Button>
            {save.isError && <p role="alert" className="text-footnote text-danger">{save.error.message}</p>}
            {notice && <p role="status" className="text-footnote text-success">{notice}</p>}
          </div>
        </form>
      </section>

      <section aria-labelledby="history-heading" className="flex flex-col gap-4">
        <div>
          <SectionHeading id="history-heading">Bitemporal history</SectionHeading>
          <p className="mt-1 text-footnote text-label-secondary">Valid time asks when a claim applies. Belief time asks what Mnemos knew then.</p>
        </div>
        <MemoryFilterBar filters={filters} onChange={setFilters} />
        {history.isPending ? (
          <div className="flex flex-col gap-2"><Skeleton label="Loading memory history" className="h-20 w-full" /><Skeleton className="h-20 w-full" /></div>
        ) : history.isError ? (
          <div role="alert" className="flex flex-wrap items-center gap-3 border-l-2 border-danger pl-3 text-callout text-danger">
            The history could not be loaded ({history.error.message}).
            <Button rank="plain" onClick={() => void history.refetch()}>Try again</Button>
          </div>
        ) : history.data.claims.length === 0 ? (
          <EmptyState icon={Brain} title="No claims at this time" description="Nothing was true, or believed, at the times chosen. Clear the two time filters, or record a claim above." headingLevel={3} />
        ) : (
          <div className="grid grid-cols-1 gap-8 @xl/content:grid-cols-[minmax(0,1fr)_18rem]">
            <ol aria-label="Memory claims" className="flex flex-col border-t border-separator">
              {history.data.claims.map((claim) => {
                const live = claim.status === "active";
                return (
                  <li key={claim.id} className="flex flex-col gap-2 border-b border-separator py-4">
                    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                      <p className="text-callout font-semibold text-label">
                        {claim.subject.display_name} · <span className="font-mono font-normal">{claim.predicate}</span>
                      </p>
                      <span className={`status-label ${live ? "text-success" : claim.status === "superseded" ? "text-warning" : "text-label-secondary"}`}>
                        {claim.status}
                      </span>
                    </div>
                    <p className={`font-serif text-reading leading-relaxed ${live ? "text-label" : "text-label-secondary line-through decoration-rubric"}`}>
                      {claim.object_text}
                    </p>
                    <dl className="grid gap-x-6 gap-y-1 font-mono text-caption text-label-secondary @xl/content:grid-cols-2">
                      <div><dt className="inline uppercase tracking-caps">Valid </dt><dd className="inline">{formatRange(claim.valid_from, claim.valid_to)}</dd></div>
                      <div><dt className="inline uppercase tracking-caps">Believed </dt><dd className="inline">{formatRange(claim.recorded_at, claim.retracted_at)}</dd></div>
                    </dl>
                    <p className="text-caption text-label-secondary">
                      Recorded <RelativeTime value={claim.recorded_at} form="long" /> · {claim.kind} · confidence {claim.confidence}
                    </p>
                    {claim.retracted_at === null && (
                      <div className="-ml-2 flex flex-wrap gap-1">
                        <Button rank="plain" className="!px-2" onClick={() => beginSupersede(claim)}><RotateCcw className="size-4" strokeWidth={1.5} aria-hidden="true" />Supersede</Button>
                        <Button rank="plain" className="!px-2" disabled={retract.isPending} onClick={() => retract.mutate(claim.id)}><XCircle className="size-4" strokeWidth={1.5} aria-hidden="true" />Retract</Button>
                      </div>
                    )}
                  </li>
                );
              })}
            </ol>
            <Revisions history={history.data} />
          </div>
        )}
      </section>
    </div>
  );
}

/**
 * Every supersession in view, as an editor's revision mark: the old value
 * struck, the new one beside it, and the date the new one took effect. A
 * supersession is never an overwrite (C5) — both claims stay in the history
 * above — so this reads what changed into what, rather than raw edge ids.
 */
function Revisions({ history }: { history: MemoryHistory }) {
  const byId = new Map(history.claims.map((claim) => [claim.id, claim]));
  const revisions = history.edges
    .filter((edge) => edge.kind === "supersedes")
    .map((edge) => ({ edge, current: byId.get(edge.source_id), previous: byId.get(edge.target_id) }));

  return (
    <aside aria-labelledby="revisions-heading" className="flex flex-col gap-3 border-l-2 border-separator pl-4">
      <h3 id="revisions-heading" className="font-mono text-caption uppercase tracking-caps text-label-secondary">
        Revisions
      </h3>
      {revisions.length === 0 ? (
        <p className="text-footnote text-label-secondary">Nothing in this view has been superseded.</p>
      ) : (
        <ul className="flex flex-col gap-4 text-footnote">
          {revisions.map(({ edge, current, previous }) => (
            <li key={edge.id} className="flex flex-col gap-1">
              {current !== undefined && (
                <p className="font-semibold text-label">
                  {current.subject.display_name} · <span className="font-mono font-normal">{current.predicate}</span>
                </p>
              )}
              {current !== undefined && previous !== undefined ? (
                <RevisionMark
                  previous={previous.object_text}
                  current={current.object_text}
                  effective={formatDay(current.valid_from)}
                />
              ) : (
                // One end of the edge is outside the current filters.
                <p className="font-mono text-caption text-label-secondary">
                  {edge.source_id.slice(0, 8)} supersedes {edge.target_id.slice(0, 8)} (outside this view)
                </p>
              )}
              {edge.rationale && <p className="text-caption text-label-secondary">{edge.rationale}</p>}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}

function formatDay(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(value));
}

function Field({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <label className={`field-label ${className}`.trim()}>{label}{children}</label>;
}

function MemoryFilterBar({ filters, onChange }: { filters: MemoryFilters; onChange: (next: MemoryFilters) => void }) {
  return <div className="grid grid-cols-1 gap-3 @xl/content:grid-cols-4"><Field label="Subject reference"><input className={INPUT} value={filters.subjectRef ?? ""} onChange={(event) => onChange({ ...filters, subjectRef: event.target.value })} /></Field><Field label="Valid at"><input type="datetime-local" className={INPUT} value={toLocalDateTime(filters.asOf)} onChange={(event) => onChange({ ...filters, asOf: localToIso(event.target.value) })} /></Field><Field label="Believed at"><input type="datetime-local" className={INPUT} value={toLocalDateTime(filters.believedAt)} onChange={(event) => onChange({ ...filters, believedAt: localToIso(event.target.value) })} /></Field><label className="hit-target flex items-center gap-2 self-end text-footnote font-semibold text-label-secondary"><input type="checkbox" checked={filters.includeRetracted ?? true} onChange={(event) => onChange({ ...filters, includeRetracted: event.target.checked })} />Include retracted</label></div>;
}

function toWrite(draft: Draft): MemoryWrite {
  return { subject_kind: draft.subjectKind, subject_ref: draft.subjectRef, subject_name: draft.subjectName, predicate: draft.predicate, object_text: draft.objectText, kind: draft.kind, scope: {}, valid_from: localToIso(draft.validFrom) || null, valid_to: localToIso(draft.validTo) || null, confidence: Number(draft.confidence) };
}

function localToIso(value: string): string | undefined { return value ? new Date(value).toISOString() : undefined; }
function toLocalDateTime(value: string | undefined): string { if (!value) return ""; const date = new Date(value); const offset = date.getTimezoneOffset() * 60_000; return new Date(date.getTime() - offset).toISOString().slice(0, 16); }
function formatRange(from: string, to: string | null): string { return `${formatDay(from)} → ${to === null || to.startsWith("9999-") ? "open" : formatDay(to)}`; }

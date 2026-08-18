"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, GitBranch, RotateCcw, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  createMemory,
  fetchMemoryHistory,
  MEMORY_QUERY_KEY,
  retractMemory,
  supersedeMemory,
  type MemoryClaim,
  type MemoryFilters,
  type MemoryWrite,
} from "@/lib/memory/api";

const INPUT = "hit-target w-full rounded-md border border-separator bg-bg px-3 text-callout text-label outline-none focus-visible:ring-2 focus-visible:ring-accent";
const TEXTAREA = `${INPUT} min-h-24 py-2`;

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
      <header className="flex flex-col gap-2">
        <h1 className="text-large-title font-semibold tracking-title text-label">Memory</h1>
        <p className="text-callout leading-relaxed text-label-secondary">
          Record durable claims without overwriting history. Facts with the same subject, predicate, scope and overlapping validity supersede atomically; the timeline below can be reconstructed on either clock.
        </p>
      </header>

      <section aria-labelledby="write-heading" className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-3">
          <h2 id="write-heading" className="text-title-3 font-semibold tracking-title">
            {superseding ? "Supersede claim" : "Record a claim"}
          </h2>
          {superseding && <Button rank="plain" onClick={() => { setSuperseding(null); setDraft(EMPTY_DRAFT); }}>Cancel</Button>}
        </div>
        {superseding && (
          <p className="rounded-md bg-accent-tint p-3 text-footnote text-accent">
            The prior claim remains in belief-time history; this form creates its immutable replacement.
          </p>
        )}
        <form className="grid gap-4 rounded-lg bg-bg-secondary p-4 md:grid-cols-2" onSubmit={(event) => { event.preventDefault(); setNotice(null); save.mutate(); }}>
          <Field label="Subject type"><input required className={INPUT} value={draft.subjectKind} onChange={(event) => setDraft({ ...draft, subjectKind: event.target.value })} /></Field>
          <Field label="Subject reference"><input required className={INPUT} placeholder="employee:ada" value={draft.subjectRef} onChange={(event) => setDraft({ ...draft, subjectRef: event.target.value })} /></Field>
          <Field label="Subject name"><input required className={INPUT} placeholder="Ada Lovelace" value={draft.subjectName} onChange={(event) => setDraft({ ...draft, subjectName: event.target.value })} /></Field>
          <Field label="Predicate"><input required className={INPUT} placeholder="prefers_editor" value={draft.predicate} onChange={(event) => setDraft({ ...draft, predicate: event.target.value })} /></Field>
          <Field label="Claim kind"><select className={INPUT} value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as MemoryWrite["kind"] })}><option value="fact">Fact</option><option value="preference">Preference</option><option value="decision">Decision</option><option value="observation">Observation</option></select></Field>
          <Field label="Confidence"><input required type="number" min="0" max="1" step="0.01" className={INPUT} value={draft.confidence} onChange={(event) => setDraft({ ...draft, confidence: event.target.value })} /></Field>
          <Field label="Valid from"><input type="datetime-local" className={INPUT} value={draft.validFrom} onChange={(event) => setDraft({ ...draft, validFrom: event.target.value })} /></Field>
          <Field label="Valid to"><input type="datetime-local" className={INPUT} value={draft.validTo} onChange={(event) => setDraft({ ...draft, validTo: event.target.value })} /></Field>
          <Field label="Claim" className="md:col-span-2"><textarea required className={TEXTAREA} value={draft.objectText} onChange={(event) => setDraft({ ...draft, objectText: event.target.value })} /></Field>
          <div className="flex flex-wrap items-center gap-3 md:col-span-2">
            <Button rank="filled" type="submit" disabled={save.isPending}>{superseding ? "Create replacement" : "Save claim"}</Button>
            {save.isError && <p role="alert" className="text-footnote text-danger">{save.error.message}</p>}
            {notice && <p role="status" className="text-footnote text-success">{notice}</p>}
          </div>
        </form>
      </section>

      <section aria-labelledby="history-heading" className="flex flex-col gap-4">
        <div>
          <h2 id="history-heading" className="text-title-3 font-semibold tracking-title">Bitemporal history</h2>
          <p className="mt-1 text-footnote text-label-secondary">Valid time asks when a claim applies. Belief time asks what Mnemos knew then.</p>
        </div>
        <MemoryFilterBar filters={filters} onChange={setFilters} />
        {history.isPending ? (
          <div className="flex flex-col gap-2"><Skeleton label="Loading memory history" className="h-24 w-full" /><Skeleton className="h-24 w-full" /></div>
        ) : history.isError ? (
          <p role="alert" className="text-callout text-danger">{history.error.message}</p>
        ) : history.data.claims.length === 0 ? (
          <EmptyState icon={Brain} title="No claims at this time" description="Record a claim above, or broaden the two time filters." headingLevel={3} />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <ol aria-label="Memory claims" className="flex flex-col gap-3">
              {history.data.claims.map((claim) => (
                <li key={claim.id} className="rounded-lg border border-separator bg-bg-secondary p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div><p className="text-callout font-semibold text-label">{claim.subject.display_name} · {claim.predicate}</p><p className="mt-1 text-footnote text-label-secondary">{claim.object_text}</p></div>
                    <span className="rounded-full bg-fill-tertiary px-2 py-1 text-caption font-semibold uppercase text-label-secondary">{claim.status}</span>
                  </div>
                  <dl className="mt-3 grid gap-2 text-caption text-label-tertiary sm:grid-cols-2">
                    <div><dt className="font-semibold">Valid time</dt><dd>{formatRange(claim.valid_from, claim.valid_to)}</dd></div>
                    <div><dt className="font-semibold">Belief time</dt><dd>{formatRange(claim.recorded_at, claim.retracted_at)}</dd></div>
                  </dl>
                  {claim.retracted_at === null && (
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button rank="tinted" onClick={() => beginSupersede(claim)}><RotateCcw className="size-4" aria-hidden="true" />Supersede</Button>
                      <Button rank="plain" disabled={retract.isPending} onClick={() => retract.mutate(claim.id)}><XCircle className="size-4" aria-hidden="true" />Retract</Button>
                    </div>
                  )}
                </li>
              ))}
            </ol>
            <aside aria-labelledby="lineage-heading" className="rounded-lg bg-bg-tertiary p-4">
              <h3 id="lineage-heading" className="flex items-center gap-2 text-callout font-semibold text-label"><GitBranch className="size-4" aria-hidden="true" />Lineage</h3>
              {history.data.edges.length === 0 ? <p className="mt-2 text-footnote text-label-secondary">No supersession edges in this view.</p> : <ul className="mt-3 flex flex-col gap-3 text-footnote">{history.data.edges.map((edge) => <li key={edge.id}><p className="font-semibold text-label">{edge.kind.replaceAll("_", " ")}</p><p className="break-all text-label-secondary">{edge.source_id} → {edge.target_id}</p>{edge.rationale && <p className="mt-1 text-label-tertiary">{edge.rationale}</p>}</li>)}</ul>}
            </aside>
          </div>
        )}
      </section>
    </div>
  );
}

function Field({ label, children, className = "" }: { label: string; children: ReactNode; className?: string }) {
  return <label className={`flex flex-col gap-1 text-footnote font-semibold text-label-secondary ${className}`}>{label}{children}</label>;
}

function MemoryFilterBar({ filters, onChange }: { filters: MemoryFilters; onChange: (next: MemoryFilters) => void }) {
  return <div className="grid gap-3 rounded-lg bg-bg-tertiary p-3 md:grid-cols-4"><Field label="Subject reference"><input className={INPUT} value={filters.subjectRef ?? ""} onChange={(event) => onChange({ ...filters, subjectRef: event.target.value })} /></Field><Field label="Valid at"><input type="datetime-local" className={INPUT} value={toLocalDateTime(filters.asOf)} onChange={(event) => onChange({ ...filters, asOf: localToIso(event.target.value) })} /></Field><Field label="Believed at"><input type="datetime-local" className={INPUT} value={toLocalDateTime(filters.believedAt)} onChange={(event) => onChange({ ...filters, believedAt: localToIso(event.target.value) })} /></Field><label className="hit-target flex items-center gap-2 self-end text-footnote font-semibold text-label-secondary"><input type="checkbox" checked={filters.includeRetracted ?? true} onChange={(event) => onChange({ ...filters, includeRetracted: event.target.checked })} />Include retracted</label></div>;
}

function toWrite(draft: Draft): MemoryWrite {
  return { subject_kind: draft.subjectKind, subject_ref: draft.subjectRef, subject_name: draft.subjectName, predicate: draft.predicate, object_text: draft.objectText, kind: draft.kind, scope: {}, valid_from: localToIso(draft.validFrom) || null, valid_to: localToIso(draft.validTo) || null, confidence: Number(draft.confidence) };
}

function localToIso(value: string): string | undefined { return value ? new Date(value).toISOString() : undefined; }
function toLocalDateTime(value: string | undefined): string { if (!value) return ""; const date = new Date(value); const offset = date.getTimezoneOffset() * 60_000; return new Date(date.getTime() - offset).toISOString().slice(0, 16); }
function formatRange(from: string, to: string | null): string { return `${new Date(from).toLocaleString()} → ${to === null || to.startsWith("9999-") ? "open" : new Date(to).toLocaleString()}`; }

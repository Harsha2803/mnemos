import type { ReactNode } from "react";

export type RevisionMarkProps = {
  /** What was believed, or cited, before. Struck through. */
  previous: ReactNode;
  /** What replaced it. */
  current: ReactNode;
  /** When the replacement took effect, already formatted for reading. */
  effective?: string;
  /** Why, in a few words — shown after the date. */
  note?: string;
  className?: string;
};

/**
 * Supersession, drawn the way an editor marks a revision: the old value struck
 * through in the rubric, the new value beside it, and the date it took effect.
 *
 * Mnemos never overwrites a claim or a document revision (C5, C6); it records
 * that one replaced another. A coloured "superseded" badge says *that* it
 * happened. A revision mark says *what changed into what, and when*, which is
 * the question a reader actually has.
 *
 * `<del>` and `<ins>` carry the meaning, and because many screen readers do not
 * announce them, each half also says in words what it is.
 */
export function RevisionMark({ previous, current, effective, note, className = "" }: RevisionMarkProps) {
  return (
    <span className={`revision-mark inline-flex flex-wrap items-baseline gap-x-2 gap-y-1 ${className}`.trim()}>
      <del className="text-label-secondary decoration-rubric decoration-2">
        <span className="sr-only">Superseded: </span>
        {previous}
      </del>
      <span aria-hidden="true" className="text-rubric">
        →
      </span>
      <ins className="rounded-sm bg-rubric-tint px-1 text-label no-underline">
        <span className="sr-only">Replaced by: </span>
        {current}
      </ins>
      {(effective !== undefined || note !== undefined) && (
        <span className="font-mono text-caption text-label-secondary">
          {[effective !== undefined ? `effective ${effective}` : null, note].filter(Boolean).join(" · ")}
        </span>
      )}
    </span>
  );
}

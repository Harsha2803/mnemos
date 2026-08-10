"use client";

import { Layers } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";
import { useInspectorSelection } from "@/lib/inspector/SelectionProvider";

/**
 * The inspector is the feature — the bundle viewer that makes the compiled
 * context legible instead of a claim in a README. It gets a permanent home on
 * the right and collapses rather than disappearing from the mental model
 * (DesignSystem §1).
 *
 * `A2` gives it its first real content: the source passage behind a clicked
 * citation, with the character span it came from. That is not yet the full
 * context bundle — what was admitted, what was excluded, and the budget spend
 * are `C4`, and the empty state still says so — but it is a real answer to
 * "where did that claim come from" rather than a placeholder.
 */
export function InspectorContent() {
  const { selection } = useInspectorSelection();

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
            description="Click a citation in an answer to see the passage it came from. The full context bundle — what was admitted, what was excluded and why — arrives with the context layer."
            headingLevel={3}
          />
        </div>
      ) : (
        <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
          <div className="flex flex-col gap-1">
            <span className="text-footnote font-semibold text-label-secondary">
              Source [{selection.citation.marker}]
            </span>
            <p className="text-callout font-semibold text-label">
              {selection.citation.page_number !== null
                ? `Page ${selection.citation.page_number}`
                : "Document passage"}
            </p>
            <p className="text-footnote text-label-secondary">
              Characters {selection.citation.start_char}–{selection.citation.end_char}
              {selection.citation.score !== null &&
                ` · relevance ${selection.citation.score.toFixed(2)}`}
            </p>
          </div>

          <blockquote className="whitespace-pre-wrap rounded-lg border-l-2 border-accent bg-bg-tertiary p-3 text-footnote leading-relaxed text-label">
            {selection.citation.quoted_text}
          </blockquote>
        </div>
      )}
    </div>
  );
}

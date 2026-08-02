import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

export type EmptyStateProps = {
  icon: LucideIcon;
  /** One line saying what goes here. Becomes the accessible heading. */
  title: string;
  description?: string;
  /**
   * The one action that fills the emptiness — omitted only when there is
   * genuinely nothing the user can do yet. An action that does not work is
   * worse than none, because it reads as a bug rather than as a boundary.
   */
  action?: ReactNode;
  /** Heading level, so the state slots into the page outline rather than over it. */
  headingLevel?: 2 | 3 | 4;
  className?: string;
};

/**
 * Every list gets one. An empty pane with no explanation reads as a bug — the
 * user cannot tell "nothing here yet" from "this failed to load", and will
 * assume the worse of the two (DesignSystem §4).
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  headingLevel = 2,
  className = "",
}: EmptyStateProps) {
  const Heading = `h${headingLevel}` as const;

  return (
    <div
      className={[
        "flex flex-col items-center justify-center gap-3 px-6 py-10 text-center",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <Icon
        className="size-7 text-label-tertiary"
        strokeWidth={1.5}
        aria-hidden="true"
      />
      <Heading className="text-headline font-semibold text-label">{title}</Heading>
      {description !== undefined && (
        <p className="measure text-subheadline text-label-secondary">{description}</p>
      )}
      {action}
    </div>
  );
}

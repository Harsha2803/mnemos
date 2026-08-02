import type { ReactNode } from "react";

export type ListProps = {
  /** The list's accessible name. Required — an unnamed list of things is a pile. */
  label: string;
  children: ReactNode;
  className?: string;
};

/**
 * Grouped-inset list: a rounded container on `--bg-secondary` with hairline
 * separators **inset to the text origin** rather than full-bleed.
 *
 * The inset is the whole point. A separator that runs edge to edge cuts the
 * container in half; one that starts where the text starts reads as a division
 * *within* a group. It is a small detail and it is most of what separates a
 * considered list from a default one (DesignSystem §4).
 */
export function List({ label, children, className = "" }: ListProps) {
  return (
    <ul aria-label={label} className={`list-group ${className}`.trim()}>
      {children}
    </ul>
  );
}

export type ListItemProps = {
  children: ReactNode;
  /** Icon or status dot. Its width shifts the separator inset to match. */
  leading?: ReactNode;
  trailing?: ReactNode;
  className?: string;
};

export function ListItem({ children, leading, trailing, className = "" }: ListItemProps) {
  return (
    <li
      className={[
        "list-row",
        // The separator has to start where the *text* starts, so the inset
        // depends on whether this row has a leading slot at all.
        leading === undefined ? "" : "list-row-leading",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <div className="flex min-h-11 items-center gap-3 px-4 py-2">
        {leading !== undefined && (
          <span className="flex size-5 shrink-0 items-center justify-center text-label-secondary">
            {leading}
          </span>
        )}
        <div className="min-w-0 flex-1 text-callout">{children}</div>
        {trailing !== undefined && (
          <span className="shrink-0 text-footnote text-label-secondary">{trailing}</span>
        )}
      </div>
    </li>
  );
}

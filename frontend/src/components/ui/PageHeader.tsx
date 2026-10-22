import type { ReactNode } from "react";

export type PageHeaderProps = {
  /** The page's one `<h1>`. Matches the section's name in the sidebar. */
  title: string;
  /** One or two sentences: what this screen is for, not how to use it. */
  description?: ReactNode;
  /** A control that belongs to the whole page (rarely needed). */
  action?: ReactNode;
};

/**
 * The top of every screen: the title set in the serif, a short description at
 * the reading measure, and a rule under both. One shape everywhere, so a
 * reader moving between sections never has to find the page's start again.
 */
export function PageHeader({ title, description, action }: PageHeaderProps) {
  return (
    <header className="flex flex-col gap-3 border-b border-separator pb-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="font-serif text-large-title font-semibold leading-tight tracking-title text-label">{title}</h1>
        {action}
      </div>
      {description !== undefined && (
        <p className="measure-reading text-callout leading-relaxed text-label-secondary">{description}</p>
      )}
    </header>
  );
}

/** A section's heading inside a page: interface face, one step down. */
export function SectionHeading({ id, children }: { id?: string; children: ReactNode }) {
  return (
    <h2 id={id} className="text-headline font-semibold text-label">
      {children}
    </h2>
  );
}

import type { ReactNode } from "react";

export type TableColumn<T> = {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
};

export type TableProps<T> = {
  /** The table's accessible name — an unnamed table of things is a grid. */
  caption: string;
  columns: TableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  className?: string;
};

/**
 * Genuinely tabular data — rows that share the same typed columns and invite
 * scanning down a column, not just down a list — gets a real `<table>`, not
 * an ad-hoc `<div>` grid: `<th scope="col">` is what makes a screen reader
 * announce which column a cell belongs to, a property no amount of flexbox
 * styling reproduces (DesignSystem §3, semantics). The first primitive of
 * this shape in the app — everything before it was a list or a card grid.
 *
 * Wrapped in its own horizontal scroller so a wide table never widens the
 * page itself.
 */
export function Table<T>({ caption, columns, rows, rowKey, className = "" }: TableProps<T>) {
  return (
    <div className={`overflow-x-auto rounded-xl border border-separator ${className}`.trim()}>
      <table className="w-full text-left text-callout">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-separator bg-bg-secondary">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className="whitespace-nowrap px-4 py-2 text-footnote font-semibold text-label-secondary"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-b border-separator last:border-0">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={`px-4 py-2 align-top ${column.className ?? ""}`.trim()}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

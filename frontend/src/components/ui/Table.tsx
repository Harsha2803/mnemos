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
  rowKey: (row: T, index: number) => string;
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
 * Labelled fields stack in a narrow container. Explicit roles preserve table
 * semantics in browsers that remove them when CSS changes table display.
 */
export function Table<T>({ caption, columns, rows, rowKey, className = "" }: TableProps<T>) {
  return (
    <div
      className={`table-region min-w-0 max-w-full overflow-auto rounded-lg border border-separator ${className}`.trim()}
    >
      <table role="table" className="responsive-table w-full text-left text-callout">
        <caption className="sr-only">{caption}</caption>
        <thead role="rowgroup">
          <tr role="row" className="border-b border-separator bg-bg-secondary">
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                role="columnheader"
                className="whitespace-nowrap px-4 py-2 text-footnote font-semibold text-label-secondary"
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody role="rowgroup">
          {rows.map((row, index) => (
            <tr
              role="row"
              key={rowKey(row, index)}
              className="border-b border-separator last:border-0"
            >
              {columns.map((column) => (
                <td
                  key={column.key}
                  role="cell"
                  className={`px-4 py-2 align-top ${column.className ?? ""}`.trim()}
                >
                  <span
                    className="table-field-label text-footnote font-semibold text-label-secondary"
                    aria-hidden="true"
                  >
                    {column.header}
                  </span>
                  <div className="min-w-0">{column.render(row)}</div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

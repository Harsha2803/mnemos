import { ShieldAlert, TriangleAlert } from "lucide-react";

import type { Nl2SqlResult, Nl2SqlVerdict, SqlCellValue } from "@/lib/chat/stream";

export type SqlPanelProps = {
  result: Nl2SqlResult;
};

/** Plain words for each guard outcome — the verdict alone (`rejected_write`) is not a sentence. */
const VERDICT_LABEL: Record<Nl2SqlVerdict, string> = {
  allowed: "Allowed",
  rejected_write: "Refused — this statement would have written to the database",
  rejected_unauthorized_table: "Refused — this statement reached a table it is not authorized to read",
  rejected_unparseable: "Refused — this statement could not be parsed as a single read",
  rejected_too_complex: "Refused — this statement was too complex to verify as read-only",
};

/**
 * The generated SQL, and either a result grid or a refusal — never both. Full
 * content width rather than the `--measure` prose column (DesignSystem §5
 * deliverable 5 brief): tabular data is exactly the case the 46rem measure
 * exists to *not* constrain.
 *
 * **The denial state is the reason this component exists.** TRACKER §5: "the
 * refusal is a screen a stranger can produce on purpose, not a log line." It
 * is visually distinct from the result state (a labelled banner, not a red
 * border alone — DesignSystem §3, colour is never the only signal) and pairs
 * `--danger` with an icon and a plain-word label so it reads correctly to a
 * screen reader, not only to a sighted user scanning for red.
 */
export function SqlPanel({ result }: SqlPanelProps) {
  const refused = result.verdict !== "allowed";
  // The guard said ALLOWED but the database itself failed (e.g. a statement
  // timeout) — a different failure than a guard denial, so it gets its own
  // labelled state rather than collapsing into the same banner.
  const executionFailed = !refused && !result.executed;

  return (
    <div className="flex w-full flex-col gap-3 rounded-lg border border-separator bg-bg-secondary p-4">
      {refused && (
        <div className="flex items-start gap-2 rounded-md border border-danger bg-bg px-3 py-2 text-footnote text-danger">
          <ShieldAlert className="size-4 shrink-0 translate-y-0.5" strokeWidth={1.5} aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <span className="font-semibold">{VERDICT_LABEL[result.verdict]}</span>
            <span className="text-label-secondary">
              Mnemos did not run this query — it only reads.
            </span>
            {result.verdict_detail !== null && (
              <span className="text-label-secondary">Reason: {result.verdict_detail}</span>
            )}
          </div>
        </div>
      )}

      {executionFailed && (
        <div className="flex items-start gap-2 rounded-md border border-danger bg-bg px-3 py-2 text-footnote text-danger">
          <TriangleAlert className="size-4 shrink-0 translate-y-0.5" strokeWidth={1.5} aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <span className="font-semibold">
              Allowed by the read-only guard, but the database could not run it
            </span>
            {result.error_code !== null && (
              <span className="text-label-secondary">Error: {result.error_code}</span>
            )}
            {result.error_detail !== null && (
              <span className="text-label-secondary">{result.error_detail}</span>
            )}
          </div>
        </div>
      )}

      <pre className="overflow-x-auto rounded-md bg-bg-tertiary p-3 text-footnote text-label">
        <code className="font-mono">{result.sql}</code>
      </pre>

      {result.executed && (
        <>
          <div className="overflow-x-auto rounded-md border border-separator">
            <table className="w-full border-collapse text-left text-footnote">
              <caption className="sr-only">Query results</caption>
              <thead>
                <tr>
                  {result.columns.map((column) => (
                    <th
                      key={column}
                      scope="col"
                      className="border-b border-separator bg-bg-tertiary px-3 py-2 font-semibold text-label"
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row, rowIndex) => (
                  <tr key={rowIndex}>
                    {row.map((cell, cellIndex) => (
                      <td
                        key={cellIndex}
                        className="border-b border-separator px-3 py-2 text-label-secondary"
                      >
                        {formatCell(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.truncated && (
            <p className="text-footnote text-label-tertiary">
              Showing the first {result.rows.length} rows — more were available and were not
              fetched.
            </p>
          )}
        </>
      )}
    </div>
  );
}

function formatCell(value: SqlCellValue): string {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

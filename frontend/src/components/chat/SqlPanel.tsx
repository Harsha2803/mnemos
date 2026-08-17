"use client";

import { Check, Copy, Database, ShieldAlert, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import type { Nl2SqlResult, Nl2SqlVerdict, SqlCellValue } from "@/lib/chat/stream";

export type SqlPanelProps = { result: Nl2SqlResult };

const VERDICT_LABEL: Record<Nl2SqlVerdict, string> = {
  allowed: "Allowed",
  rejected_write: "Refused — this statement would have written to the database",
  rejected_unauthorized_table: "Refused — this statement reached a table it is not authorized to read",
  rejected_unparseable: "Refused — this statement could not be parsed as a single read",
  rejected_too_complex: "Refused — this statement was too complex to verify as read-only",
};

export function SqlPanel({ result }: SqlPanelProps) {
  const refused = result.verdict !== "allowed";
  const executionFailed = !refused && !result.executed;
  const [copied, setCopied] = useState<"sql" | "table" | null>(null);

  async function copy(kind: "sql" | "table", value: string): Promise<void> {
    await navigator.clipboard.writeText(value);
    setCopied(kind);
    window.setTimeout(() => setCopied(null), 1500);
  }

  return (
    <div className="flex w-full flex-col gap-3 rounded-lg border border-separator bg-bg-secondary p-4">
      {refused && (
        <div className="flex items-start gap-2 rounded-md border border-danger bg-bg px-3 py-2 text-footnote text-danger">
          <ShieldAlert className="size-4 shrink-0 translate-y-0.5" strokeWidth={1.5} aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <span className="font-semibold">{VERDICT_LABEL[result.verdict]}</span>
            <span className="text-label-secondary">Mnemos did not run this query — it only reads.</span>
            {result.denied_tables.length > 0 && <span className="font-semibold">Blocked: {result.denied_tables.join(", ")}</span>}
            {result.verdict_detail !== null && <span className="text-label-secondary">Reason: {result.verdict_detail}</span>}
          </div>
        </div>
      )}

      {executionFailed && (
        <div className="flex items-start gap-2 rounded-md border border-danger bg-bg px-3 py-2 text-footnote text-danger">
          <TriangleAlert className="size-4 shrink-0 translate-y-0.5" strokeWidth={1.5} aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <span className="font-semibold">Allowed by the read-only guard, but the database could not run it</span>
            {result.error_code !== null && <span className="text-label-secondary">Error: {result.error_code}</span>}
            {result.error_detail !== null && <span className="text-label-secondary">{result.error_detail}</span>}
          </div>
        </div>
      )}

      <dl className="flex flex-wrap gap-x-5 gap-y-2 border-y border-separator py-2 text-footnote">
        <Meta label="Verdict" value={result.verdict === "allowed" ? "Allowed" : "Refused"} tone={refused ? "text-danger" : "text-success"} />
        <Meta label="Attempt" value={String(result.attempt)} />
        <Meta label="Duration" value={result.duration_ms === null ? "—" : `${result.duration_ms} ms`} />
        <Meta label="Rows" value={result.row_count === null ? "—" : String(result.row_count)} />
        <Meta label="Result" value={result.truncated ? "Truncated" : "Complete"} tone={result.truncated ? "text-warning" : undefined} />
      </dl>

      <div className="flex flex-wrap gap-2 text-footnote">
        {result.authorized_tables.map((table) => <span key={table} className="rounded-full bg-fill-tertiary px-2 py-1 text-label-secondary">Authorized: {table}</span>)}
        {result.denied_tables.map((table) => <span key={table} className="rounded-full bg-fill-tertiary px-2 py-1 font-semibold text-danger">Denied: {table}</span>)}
      </div>

      <details open className="group rounded-md bg-bg-tertiary">
        <summary className="hit-target flex cursor-pointer items-center justify-between px-3 text-footnote font-semibold text-label">Generated SQL <span className="text-label-tertiary group-open:hidden">Show</span><span className="hidden text-label-tertiary group-open:inline">Hide</span></summary>
        <div className="border-t border-separator">
          <div className="flex justify-end p-1">
            <Button rank="plain" className="!px-2 text-footnote" aria-label="Copy SQL" onClick={() => void copy("sql", result.sql)}>
              {copied === "sql" ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}{copied === "sql" ? "Copied" : "Copy SQL"}
            </Button>
          </div>
          <pre className="overflow-x-auto px-3 pb-3 text-footnote text-label"><code className="font-mono">{result.sql}</code></pre>
        </div>
      </details>

      {result.executed && result.rows.length === 0 && (
        <div className="flex items-center gap-3 rounded-md border border-separator p-4 text-footnote text-label-secondary">
          <Database className="size-5" aria-hidden="true" />The query ran successfully and returned no rows.
        </div>
      )}

      {result.executed && result.rows.length > 0 && (
        <>
          <div className="flex justify-end">
            <Button rank="plain" className="!px-2 text-footnote" aria-label="Copy result table" onClick={() => void copy("table", tableAsTsv(result))}>
              {copied === "table" ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}{copied === "table" ? "Copied" : "Copy table"}
            </Button>
          </div>
          <div className="max-h-96 overflow-auto rounded-md border border-separator">
            <table className="w-full border-collapse text-left text-footnote">
              <caption className="sr-only">Query results</caption>
              <thead className="sticky top-0 z-10">
                <tr>{result.columns.map((column) => <th key={column} scope="col" className="border-b border-separator bg-bg-tertiary px-3 py-2 font-semibold text-label">{column}</th>)}</tr>
              </thead>
              <tbody>{result.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex} className="border-b border-separator px-3 py-2 text-label-secondary">{formatCell(cell)}</td>)}</tr>)}</tbody>
            </table>
          </div>
          {result.truncated && <p className="text-footnote text-label-tertiary">Showing the first {result.rows.length} rows — more were available and were not fetched.</p>}
        </>
      )}
    </div>
  );
}

function Meta({ label, value, tone = "text-label" }: { label: string; value: string; tone?: string }) { return <div><dt className="inline text-label-secondary">{label}: </dt><dd className={`inline font-semibold ${tone}`}>{value}</dd></div>; }
function formatCell(value: SqlCellValue): string { if (value === null) return "—"; if (typeof value === "boolean") return value ? "true" : "false"; return String(value); }
function tableAsTsv(result: Nl2SqlResult): string { return [result.columns, ...result.rows].map((row) => row.map(formatCell).join("\t")).join("\n"); }

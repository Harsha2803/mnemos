"use client";

import { Check, Copy, Database, ShieldAlert, TriangleAlert } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Table } from "@/components/ui/Table";
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
    <div className="flex min-w-0 w-full max-w-full flex-col gap-3 border-l-2 border-separator pl-4">
      {refused && (
        <div className="flex items-start gap-2 border-l-2 border-danger py-1 pl-3 text-footnote text-danger">
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
        <div className="flex items-start gap-2 border-l-2 border-danger py-1 pl-3 text-footnote text-danger">
          <TriangleAlert className="size-4 shrink-0 translate-y-0.5" strokeWidth={1.5} aria-hidden="true" />
          <div className="flex flex-col gap-1">
            <span className="font-semibold">Allowed by the read-only guard, but the database could not run it</span>
            {result.error_code !== null && <span className="text-label-secondary">Error: {result.error_code}</span>}
            {result.error_detail !== null && <span className="text-label-secondary">{result.error_detail}</span>}
          </div>
        </div>
      )}

      <dl className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-caption">
        <Meta label="Verdict" value={result.verdict === "allowed" ? "Allowed" : "Refused"} tone={refused ? "text-danger" : "text-success"} />
        <Meta label="Attempt" value={String(result.attempt)} />
        <Meta label="Duration" value={result.duration_ms === null ? "—" : `${result.duration_ms} ms`} />
        <Meta label="Rows" value={result.row_count === null ? "—" : String(result.row_count)} />
        <Meta label="Result" value={result.truncated ? "Truncated" : "Complete"} tone={result.truncated ? "text-warning" : undefined} />
      </dl>

      <div className="flex flex-wrap gap-x-4 gap-y-1 font-mono text-caption">
        {result.authorized_tables.map((table) => <span key={table} className="text-label-secondary">Authorized: <span className="text-label">{table}</span></span>)}
        {result.denied_tables.map((table) => <span key={table} className="font-semibold text-danger">Denied: {table}</span>)}
      </div>

      <details open className="group rounded-sm bg-bg-tertiary">
        <summary className="hit-target flex cursor-pointer items-center justify-between px-3 text-footnote font-semibold text-label">Generated SQL <span className="font-normal text-label-secondary group-open:hidden">Show</span><span className="hidden font-normal text-label-secondary group-open:inline">Hide</span></summary>
        <div className="border-t border-separator">
          <div className="flex justify-end p-1">
            <Button rank="plain" className="!px-2 text-footnote" aria-label="Copy SQL" onClick={() => void copy("sql", result.sql)}>
              {copied === "sql" ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}{copied === "sql" ? "Copied" : "Copy SQL"}
            </Button>
          </div>
          <pre className="overflow-x-auto px-3 pb-3 text-footnote leading-relaxed text-label"><code className="font-mono">{result.sql}</code></pre>
        </div>
      </details>

      {result.executed && result.rows.length === 0 && (
        <div className="flex items-center gap-3 border-l-2 border-separator py-1 pl-3 text-footnote text-label-secondary">
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
          <Table
            caption="Query results"
            className="max-h-96"
            columns={result.columns.map((column, index) => ({ key: String(index), header: column, render: (row: SqlCellValue[]) => formatCell(row[index] ?? null) }))}
            rows={result.rows}
            rowKey={(_, index) => String(index)}
          />
          {result.truncated && <p className="text-footnote text-label-secondary">Showing the first {result.rows.length} rows — more were available and were not fetched.</p>}
        </>
      )}
    </div>
  );
}

function Meta({ label, value, tone = "text-label" }: { label: string; value: string; tone?: string }) { return <div><dt className="inline uppercase tracking-caps text-label-secondary">{label} </dt><dd className={`inline ${tone}`}>{value}</dd></div>; }
function formatCell(value: SqlCellValue): string { if (value === null) return "—"; if (typeof value === "boolean") return value ? "true" : "false"; return String(value); }
function tableAsTsv(result: Nl2SqlResult): string { return [result.columns, ...result.rows].map((row) => row.map(formatCell).join("\t")).join("\n"); }

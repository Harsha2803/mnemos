import { Bookmark, BookmarkCheck, Check, Copy, Search } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import type { Nl2SqlResult, ToolResult } from "@/lib/chat/stream";
import type { Citation } from "@/lib/knowledge/api";

import { SqlPanel } from "./SqlPanel";

export type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** The backend-selected answer pipeline and its compact display rationale. */
  flow?: string | null;
  routeReason?: string | null;
  /** True for the one assistant bubble currently filling with tokens. */
  streaming?: boolean;
  /**
   * True for the one turn the composer just sent, false/absent for anything
   * loaded from history — the signal `MessageBubble` uses to animate a bubble
   * in only when it genuinely just appeared, not on every conversation open.
   */
  justSent?: boolean;
  /** Present on a RAG answer; the markers in `content` index into these. */
  citations?: Citation[];
  /**
   * Present on an NL2SQL answer received live in this browser session. Not
   * reconstructed from `GET /v1/chat/sessions/{id}` after a reload — the SQL,
   * verdict and rows exist only in the live `done` frame, by design (TRACKER
   * §5 deliverable 5) — so a reloaded historical `nl2sql` message renders as
   * a plain assistant bubble with no panel.
   */
  nl2sql?: Nl2SqlResult;
  /** The one MCP proposal/result attached to a live tool-routed turn. */
  tool?: ToolResult;
  /** `C3` deliverable 2 — set from `GET /chat/sessions/{id}`'s per-message
   * state, absent (never `false`) on a message still streaming in, since a
   * message cannot be bookmarked before it exists. */
  bookmarked?: boolean;
};

export type MessageBubbleProps = {
  message: DisplayMessage;
  onCitationClick?: (citation: Citation) => void;
  onMessageSelect?: () => void;
  onToggleBookmark?: () => void;
  selectedCitationId?: string;
};

const MARKER = /(\[\d+\])/g;

/**
 * User and assistant turns are distinguished by side, background *and* an
 * accessible-name label — never colour alone (DesignSystem §3). The streaming
 * bubble carries `aria-live="polite"` so a screen-reader user learns the
 * answer arrived without it being announced token by token.
 *
 * Citation markers become real buttons rather than styled spans: a control
 * that opens a panel is a button, and a `<span onClick>` is invisible to a
 * screen reader and unreachable by keyboard (DesignSystem §3, semantics).
 */
export function MessageBubble({
  message,
  onCitationClick,
  onMessageSelect,
  onToggleBookmark,
  selectedCitationId,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const [copied, setCopied] = useState(false);

  async function copyAnswer(): Promise<void> {
    await navigator.clipboard.writeText(message.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div
      id={`message-${message.id}`}
      className={[
        "flex flex-col gap-1",
        isUser ? "items-end" : "items-start",
        // Only the user's own turn animates in: its id never changes after
        // creation. The assistant bubble mounts once (empty, `streaming`)
        // and its `id` is swapped for the server's once the reply finishes
        // (`page.tsx`'s `onDone`) — animating that bubble too would replay
        // the entrance a second time right as the swap remounts it.
        message.justSent === true && isUser ? "animate-fade-in-up" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="px-1 text-footnote text-label-secondary">
        {isUser ? "You" : "Mnemos"}
      </span>
      {!isUser && message.flow != null && message.routeReason != null && (
        <span
          className="px-1 text-caption font-semibold text-info"
          aria-label={`Routed to ${flowLabel(message.flow)}: ${message.routeReason}`}
        >
          {flowLabel(message.flow)} · {message.routeReason}
        </span>
      )}
      <div
        aria-live={message.streaming === true ? "polite" : undefined}
        className={[
          "measure whitespace-pre-wrap rounded-lg px-4 py-3 text-body leading-relaxed",
          isUser ? "bg-accent-tint text-label" : "bg-bg-secondary text-label",
        ].join(" ")}
      >
        {message.content.length > 0 ? (
          renderWithCitations(message, onCitationClick, selectedCitationId)
        ) : (
          <span className="text-label-tertiary">Thinking…</span>
        )}
      </div>
      {!isUser && message.content.length > 0 && message.streaming !== true && (
        <div className="flex flex-wrap items-center gap-1 px-1">
          {onMessageSelect && (
            <Button rank="plain" className="!px-2 text-footnote" onClick={onMessageSelect}>
              <Search className="size-4" strokeWidth={1.5} aria-hidden="true" />
              Inspect answer
            </Button>
          )}
          <Button
            rank="plain"
            className="!px-2 text-footnote"
            aria-label="Copy answer"
            onClick={() => void copyAnswer()}
          >
            {copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
            {copied ? "Copied" : "Copy"}
          </Button>
          {onToggleBookmark && (
            <Button
              rank="plain"
              className="!px-2 text-footnote"
              aria-label={message.bookmarked === true ? "Remove bookmark" : "Bookmark this answer"}
              aria-pressed={message.bookmarked === true}
              onClick={onToggleBookmark}
            >
              {message.bookmarked === true ? (
                <BookmarkCheck className="size-4" aria-hidden="true" />
              ) : (
                <Bookmark className="size-4" strokeWidth={1.5} aria-hidden="true" />
              )}
              {message.bookmarked === true ? "Bookmarked" : "Bookmark"}
            </Button>
          )}
        </div>
      )}
      {!isUser && (message.citations?.length ?? 0) >= 2 && (
        <div className="flex flex-wrap gap-2 px-1" aria-label="Evidence used by this answer">
          {message.citations?.map((citation) => (
            <button
              key={citation.id}
              type="button"
              onClick={() => onCitationClick?.(citation)}
              className={[
                "hit-target rounded-full border px-3 text-footnote font-semibold transition-colors",
                citation.id === selectedCitationId
                  ? "border-accent bg-accent-tint text-accent"
                  : "border-separator bg-bg-secondary text-label-secondary hover:bg-fill-tertiary",
              ].join(" ")}
            >
              Source [{citation.marker}]
            </button>
          ))}
        </div>
      )}
      {/* Outside the `measure`-clamped bubble above, deliberately: tabular
          data wants the full content column, not the 46rem prose measure
          (DesignSystem, TRACKER §5 deliverable 5). Visible inline in the
          conversation, not only behind an inspector click. */}
      {message.nl2sql !== undefined && <SqlPanel result={message.nl2sql} />}
      {message.tool !== undefined && <ToolCallPanel result={message.tool} />}
    </div>
  );
}

function flowLabel(flow: string): string {
  if (flow === "rag") return "Documents";
  if (flow === "nl2sql") return "Data";
  if (flow === "tool") return "Tool";
  return "Chat";
}

function ToolCallPanel({ result }: { result: ToolResult }) {
  const deniedSource = result.offending_source;
  return (
    <section className="measure mt-1 flex flex-col gap-2 rounded-lg border border-separator bg-bg-secondary p-4" aria-label="Tool call state">
      <p className="text-headline font-semibold capitalize">Tool call · {result.status.replace("_", " ")}</p>
      {result.status === "pending_approval" && (
        <p className="text-callout text-label-secondary">This call is persisted and has not run. <Link className="font-semibold text-accent" href="/tools">Review it in Tools.</Link></p>
      )}
      {result.status === "succeeded" && <pre className="overflow-x-auto text-footnote">{JSON.stringify(result.result, null, 2)}</pre>}
      {result.status === "denied" && <p className="text-callout text-danger">{deniedSource !== null ? `Retrieved source “${deniedSource}” did not have enough authority.` : `Denied: ${result.denied_reason ?? "policy"}.`}</p>}
      {result.status === "failed" && <p className="text-callout text-danger">Failed: {result.error_code ?? "unknown_error"}</p>}
    </section>
  );
}

function renderWithCitations(
  message: DisplayMessage,
  onCitationClick?: (citation: Citation) => void,
  selectedCitationId?: string,
) {
  const citations = message.citations ?? [];
  if (citations.length === 0 || onCitationClick === undefined) return message.content;

  return message.content.split(MARKER).map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    if (match === null) return <span key={index}>{part}</span>;

    const marker = Number(match[1]);
    const citation = citations.find((c) => c.marker === marker);
    if (citation === undefined) return <span key={index}>{part}</span>;

    const previewId = `citation-preview-${message.id}-${citation.id}-${index}`;
    return (
      <span key={index} className="group/citation relative inline-block">
        <button
          type="button"
          aria-label={`Show source ${marker}`}
          aria-describedby={previewId}
          onClick={(event) => {
            event.stopPropagation();
            onCitationClick(citation);
          }}
          className={[
            "mx-0.5 cursor-pointer rounded-sm px-1 align-baseline text-footnote font-semibold text-accent transition-colors duration-150 ease-standard",
            citation.id === selectedCitationId ? "bg-accent-tint-hover" : "bg-accent-tint hover:bg-accent-tint-hover",
          ].join(" ")}
        >
          {part}
        </button>
        <span
          id={previewId}
          role="tooltip"
          className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 hidden w-72 -translate-x-1/2 rounded-md border border-separator bg-bg p-3 text-left text-footnote font-normal leading-relaxed text-label shadow-lg group-hover/citation:block group-focus-within/citation:block"
        >
          <span className="mb-1 block font-semibold">Source [{citation.marker}]</span>
          <span className="line-clamp-4 block">{citation.quoted_text}</span>
          <span className="mt-1 block text-label-secondary">{citationMetadata(citation)}</span>
        </span>
      </span>
    );
  });
}

function citationMetadata(citation: Citation): string {
  const parts: string[] = [];
  if (citation.page_number !== null) parts.push(`Page ${citation.page_number}`);
  if (citation.start_char !== null && citation.end_char !== null) {
    parts.push(`Characters ${citation.start_char}–${citation.end_char}`);
  }
  if (citation.score !== null) parts.push(`Relevance ${citation.score.toFixed(2)}`);
  return parts.join(" · ") || "Document passage";
}

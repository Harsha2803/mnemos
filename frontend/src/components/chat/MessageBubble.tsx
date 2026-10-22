"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { Fragment, useId, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/Button";
import { RelativeTime } from "@/components/ui/RelativeTime";
import type { Nl2SqlResult, ToolResult } from "@/lib/chat/stream";
import { contextBundleQueryKey, fetchContextBundle } from "@/lib/context/api";
import type { Citation } from "@/lib/knowledge/api";

import { SqlPanel } from "./SqlPanel";

export type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** When the server recorded it; absent only on a turn still being written. */
  createdAt?: string;
  /** The backend-selected answer pipeline and its compact display rationale. */
  flow?: string | null;
  routeReason?: string | null;
  /** True for the one assistant answer currently filling with tokens. */
  streaming?: boolean;
  /** True when the answer ended in an error rather than a reply. */
  failed?: boolean;
  /**
   * True for the one turn the composer just sent, false/absent for anything
   * loaded from history — the signal used to animate a turn in only when it
   * genuinely just appeared, not on every conversation open.
   */
  justSent?: boolean;
  /** Present on a RAG answer; the markers in `content` index into these. */
  citations?: Citation[];
  /**
   * Present on an NL2SQL answer received live in this browser session. Not
   * reconstructed from `GET /v1/chat/sessions/{id}` after a reload — the SQL,
   * verdict and rows exist only in the live `done` frame, by design (TRACKER
   * §5 deliverable 5) — so a reloaded historical `nl2sql` message renders as
   * a plain answer with no panel.
   */
  nl2sql?: Nl2SqlResult;
  /** The one MCP proposal/result attached to a live tool-routed turn. */
  tool?: ToolResult;
  /** `C3` deliverable 2 — absent (never `false`) on a message still streaming in. */
  bookmarked?: boolean;
  /** `C3` deliverable 3 — same absent-while-streaming reasoning as `bookmarked`. */
  feedback?: "up" | "down" | null;
  /**
   * Set when an optimistic bookmark or rating was rolled back because the
   * request failed: said next to the control that was pressed, not as a toast.
   */
  actionError?: string;
};

export type MessageBubbleProps = {
  message: DisplayMessage;
  onCitationClick?: (citation: Citation) => void;
  onMessageSelect?: () => void;
  onToggleBookmark?: () => void;
  /**
   * `rating: null` clears an existing rating (clicking the already-selected
   * thumb toggles it off). `comment` is attached only when the caller typed
   * one into the optional follow-up field after rating a message down.
   */
  onRate?: (rating: "up" | "down" | null, comment?: string) => void;
  /** Ask the same question again, offered on an answer that failed. */
  onRetry?: () => void;
  selectedCitationId?: string;
  /**
   * Whether the transcript is wide enough for a margin. Wide: sources sit
   * beside their paragraph as sidenotes and a numeral opens the inspector.
   * Narrow: a numeral discloses its source inline, under the paragraph.
   */
  wide?: boolean;
  /** Document titles by id, so a source is named, not numbered. */
  documentTitles?: ReadonlyMap<string, string>;
  /** Show the context-budget meter. Only the latest answer asks for its bundle. */
  showBudget?: boolean;
};

const MARKER = /(\[\d+\])/g;

/**
 * One turn of the conversation, set as a document rather than as chat bubbles.
 *
 * The question is a compact query line — "You" and what was asked, in the
 * interface face. The answer is reading text: serif, at the reading measure,
 * split into its paragraphs. Each `[n]` becomes a superscript numeral in the
 * rubric, a real button. On a wide transcript the sources sit in the margin
 * beside the paragraph that cites them; on a narrow one a numeral opens its
 * source under the paragraph. Nothing floats over the text being read.
 *
 * Who said what is carried by position, face *and* a visible label — never
 * colour alone (DesignSystem §3).
 */
export function MessageBubble(props: MessageBubbleProps) {
  const { message } = props;
  return (
    <div
      id={`message-${message.id}`}
      className={[
        "flex min-w-0 max-w-full flex-col",
        // Only the user's own turn animates in: an assistant answer is swapped
        // for the server's copy (new id) when it finishes, and replaying an
        // entrance there would flash the text the reader is on.
        message.justSent === true && message.role === "user" ? "animate-fade-in-up" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {message.role === "user" ? <QueryLine message={message} /> : <Answer {...props} />}
    </div>
  );
}

function QueryLine({ message }: { message: DisplayMessage }) {
  return (
    <div className="flex items-baseline gap-3 border-t border-separator pt-6">
      <span className="shrink-0 font-mono text-caption uppercase tracking-caps text-label-secondary">
        You
      </span>
      <p className="min-w-0 flex-1 whitespace-pre-wrap text-headline font-semibold leading-normal text-label">
        {message.content}
      </p>
    </div>
  );
}

function Answer({
  message,
  onCitationClick,
  onMessageSelect,
  onToggleBookmark,
  onRate,
  onRetry,
  selectedCitationId,
  wide = true,
  documentTitles,
  showBudget = false,
}: MessageBubbleProps) {
  const [openMarker, setOpenMarker] = useState<number | null>(null);
  const [hoveredMarker, setHoveredMarker] = useState<number | null>(null);
  const citations = message.citations ?? [];
  const paragraphs = message.content.split(/\n{2,}/);
  const finished = message.content.length > 0 && message.streaming !== true;

  function activate(citation: Citation): void {
    if (wide || onCitationClick === undefined) {
      onCitationClick?.(citation);
      return;
    }
    setOpenMarker((current) => (current === citation.marker ? null : citation.marker));
  }

  return (
    <article aria-label="Answer from Mnemos" className="mt-4 flex min-w-0 flex-col gap-3">
      <AnswerHeader message={message} />

      <div aria-busy={message.streaming === true} className="flex min-w-0 flex-col gap-4">
        {message.content.length === 0 ? (
          <p className="font-serif text-reading italic leading-relaxed text-label-secondary">
            <span className="animate-pulse">Thinking…</span>
          </p>
        ) : message.failed === true ? (
          <p className="measure-reading border-l-2 border-danger pl-3 text-callout text-label">
            <span className="mb-1 block font-mono text-caption uppercase tracking-caps text-danger">
              Not answered
            </span>
            {message.content}
          </p>
        ) : (
          paragraphs.map((paragraph, index) => {
            const cited = citationsIn(paragraph, citations);
            const open = cited.find((citation) => citation.marker === openMarker);
            return (
              <div
                key={index}
                className="grid min-w-0 grid-cols-1 gap-x-6 @[46rem]/transcript:grid-cols-[minmax(0,36rem)_13rem]"
              >
                <p className="min-w-0 whitespace-pre-wrap font-serif text-reading leading-relaxed text-label">
                  {renderParagraph(paragraph, citations, {
                    messageId: message.id,
                    onActivate: onCitationClick === undefined ? undefined : activate,
                    onHover: setHoveredMarker,
                    selectedCitationId,
                    openMarker: wide ? null : openMarker,
                    wide,
                  })}
                </p>
                {cited.length > 0 && onCitationClick !== undefined && (
                  <div className="hidden min-w-0 flex-col gap-3 pt-1 @[46rem]/transcript:flex">
                    {cited.map((citation) => (
                      <Sidenote
                        key={citation.id}
                        citation={citation}
                        title={titleFor(citation, documentTitles)}
                        active={citation.id === selectedCitationId || citation.marker === hoveredMarker}
                        onOpen={() => onCitationClick(citation)}
                        onHover={setHoveredMarker}
                      />
                    ))}
                  </div>
                )}
                {!wide && open !== undefined && onCitationClick !== undefined && (
                  <InlineSource
                    id={noteId(message.id, open.marker)}
                    citation={open}
                    title={titleFor(open, documentTitles)}
                    onOpen={() => onCitationClick(open)}
                  />
                )}
              </div>
            );
          })
        )}
      </div>

      {message.nl2sql !== undefined && <SqlPanel result={message.nl2sql} />}
      {message.tool !== undefined && <ToolCallPanel result={message.tool} />}

      {message.failed === true && onRetry !== undefined && message.streaming !== true && (
        <div>
          <Button rank="tinted" onClick={onRetry}>
            Ask again
          </Button>
        </div>
      )}

      {finished && message.failed !== true && (
        <Colophon
          message={message}
          onMessageSelect={onMessageSelect}
          onToggleBookmark={onToggleBookmark}
          onRate={onRate}
          showBudget={showBudget}
        />
      )}
    </article>
  );
}

/**
 * "Mnemos", the route stamp, and when. The stamp is a button: the route is a
 * decision, and its rationale is one press away rather than always printed.
 */
function AnswerHeader({ message }: { message: DisplayMessage }) {
  const [showWhy, setShowWhy] = useState(false);
  const whyId = useId();
  const hasRoute = message.flow != null && message.routeReason != null;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-mono text-caption uppercase tracking-caps text-label-secondary">
          Mnemos
        </span>
        {hasRoute && (
          <button
            type="button"
            aria-label={`Routed to ${flowLabel(message.flow as string)}: ${message.routeReason as string}`}
            aria-expanded={showWhy}
            aria-controls={whyId}
            onClick={() => setShowWhy((open) => !open)}
            className="stamp hit-area-inline"
          >
            {flowLabel(message.flow as string)}
          </button>
        )}
        {message.createdAt !== undefined && message.streaming !== true && (
          <RelativeTime value={message.createdAt} form="long" className="text-caption text-label-secondary" />
        )}
      </div>
      {hasRoute && (
        <p
          id={whyId}
          hidden={!showWhy}
          className="measure-reading border-l-2 border-separator pl-3 text-footnote text-label-secondary"
        >
          Answered from {flowSource(message.flow as string)}. {message.routeReason}
        </p>
      )}
    </div>
  );
}

type ParagraphOptions = {
  messageId: string;
  onActivate?: (citation: Citation) => void;
  onHover: (marker: number | null) => void;
  selectedCitationId?: string;
  openMarker: number | null;
  wide: boolean;
};

function renderParagraph(paragraph: string, citations: Citation[], options: ParagraphOptions): ReactNode {
  if (citations.length === 0 || options.onActivate === undefined) return paragraph;
  const activate = options.onActivate;

  const parts = paragraph.split(MARKER);
  return parts.map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    if (match === null) {
      // "year [1]." sets as "year¹." — a superscript hugs the word it cites.
      const next = parts[index + 1];
      const cites = next !== undefined && citations.some((c) => `[${c.marker}]` === next);
      return <Fragment key={index}>{cites ? part.trimEnd() : part}</Fragment>;
    }
    const marker = Number(match[1]);
    const citation = citations.find((candidate) => candidate.marker === marker);
    // A marker the model wrote without a matching citation stays plain text
    // rather than becoming a control that opens nothing.
    if (citation === undefined) return <Fragment key={index}>{part}</Fragment>;

    const selected = citation.id === options.selectedCitationId || options.openMarker === marker;
    return (
      <sup key={index}>
        <button
          type="button"
          aria-label={`Show source ${marker}`}
          aria-expanded={options.wide ? undefined : options.openMarker === marker}
          aria-controls={options.wide ? undefined : noteId(options.messageId, marker)}
          data-citation-marker={marker}
          onClick={(event) => {
            event.stopPropagation();
            activate(citation);
          }}
          onPointerEnter={() => options.onHover(marker)}
          onPointerLeave={() => options.onHover(null)}
          onFocus={() => options.onHover(marker)}
          onBlur={() => options.onHover(null)}
          className={[
            "citation-marker hit-area-inline",
            selected ? "bg-rubric-tint" : "",
          ].join(" ")}
        >
          {marker}
        </button>
      </sup>
    );
  });
}

function Sidenote({
  citation,
  title,
  active,
  onOpen,
  onHover,
}: {
  citation: Citation;
  title: string;
  active: boolean;
  onOpen: () => void;
  onHover: (marker: number | null) => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      onPointerEnter={() => onHover(citation.marker)}
      onPointerLeave={() => onHover(null)}
      aria-label={`Open source ${citation.marker} in the inspector: ${title}${citation.page_number !== null ? `, page ${citation.page_number}` : ""}`}
      className={[
        "sidenote hit-target flex flex-col items-start gap-1 border-l-2 py-1 pl-3 pr-1 text-left",
        active ? "sidenote-active border-rubric bg-rubric-tint" : "border-separator",
      ].join(" ")}
    >
      <span className="flex w-full items-baseline gap-1.5 text-caption">
        <span className="font-semibold text-rubric">{citation.marker}</span>
        <span className="min-w-0 truncate font-semibold text-label">{title}</span>
        {citation.page_number !== null && (
          <span className="shrink-0 font-mono text-label-secondary">p.{citation.page_number}</span>
        )}
      </span>
      <span className="line-clamp-3 font-serif text-footnote leading-snug text-label-secondary">
        {citation.quoted_text}
      </span>
    </button>
  );
}

function InlineSource({
  id,
  citation,
  title,
  onOpen,
}: {
  id: string;
  citation: Citation;
  title: string;
  onOpen: () => void;
}) {
  return (
    <div id={id} className="sidenote-inline mt-3 flex flex-col gap-2 border-l-2 border-rubric pl-3">
      <p className="flex items-baseline gap-1.5 text-caption">
        <span className="font-semibold text-rubric">{citation.marker}</span>
        <span className="font-semibold text-label">{title}</span>
        {citation.page_number !== null && (
          <span className="font-mono text-label-secondary">p.{citation.page_number}</span>
        )}
      </p>
      <blockquote className="font-serif text-callout leading-relaxed text-label">
        {citation.quoted_text}
      </blockquote>
      <div>
        <Button
          rank="plain"
          className="!px-0 text-footnote"
          aria-label={`Open source ${citation.marker} in the inspector`}
          onClick={onOpen}
        >
          Read it in context
        </Button>
      </div>
    </div>
  );
}

/**
 * What can be done with an answer, set quietly under it: words where a word
 * is clear, a glyph only for the two ratings. Feedback about a press appears
 * at the control that was pressed.
 */
function Colophon({
  message,
  onMessageSelect,
  onToggleBookmark,
  onRate,
  showBudget,
}: Pick<MessageBubbleProps, "message" | "onMessageSelect" | "onToggleBookmark" | "onRate"> & {
  showBudget: boolean;
}) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const [showCommentBox, setShowCommentBox] = useState(false);
  const [comment, setComment] = useState("");

  async function copyAnswer(): Promise<void> {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopyState("copied");
    } catch {
      setCopyState("failed");
    }
    window.setTimeout(() => setCopyState("idle"), 1800);
  }

  function handleThumbsUp(): void {
    setShowCommentBox(false);
    onRate?.(message.feedback === "up" ? null : "up");
  }

  function handleThumbsDown(): void {
    if (message.feedback === "down") {
      setShowCommentBox(false);
      onRate?.(null);
      return;
    }
    onRate?.("down");
    setShowCommentBox(true);
  }

  function submitComment(): void {
    const trimmed = comment.trim();
    setShowCommentBox(false);
    setComment("");
    if (trimmed.length > 0) onRate?.("down", trimmed);
  }

  const quiet = "!px-2 text-footnote !font-medium !text-label-secondary hover:!text-label";

  return (
    <div className="flex flex-col gap-2">
      <div className="-ml-2 flex flex-wrap items-center gap-x-1">
        {onMessageSelect && (
          <Button rank="plain" className={quiet} aria-label="Inspect answer" onClick={onMessageSelect}>
            Inspect
          </Button>
        )}
        <Button rank="plain" className={quiet} aria-label="Copy answer" onClick={() => void copyAnswer()}>
          {copyState === "copied" && <Check className="size-3.5" aria-hidden="true" />}
          {copyState === "copied" ? "Copied" : copyState === "failed" ? "Copy failed" : "Copy"}
        </Button>
        {onToggleBookmark && (
          <Button
            rank="plain"
            className={quiet}
            aria-label={message.bookmarked === true ? "Remove bookmark" : "Bookmark this answer"}
            aria-pressed={message.bookmarked === true}
            onClick={onToggleBookmark}
          >
            {message.bookmarked === true ? "Bookmarked" : "Bookmark"}
          </Button>
        )}
        {onRate && (
          <>
            <Button
              rank="plain"
              className={quiet}
              aria-label={message.feedback === "up" ? "Remove rating" : "Good answer"}
              aria-pressed={message.feedback === "up"}
              onClick={handleThumbsUp}
            >
              <ThumbsUp
                className="size-4"
                strokeWidth={1.5}
                fill={message.feedback === "up" ? "currentColor" : "none"}
                aria-hidden="true"
              />
            </Button>
            <Button
              rank="plain"
              className={quiet}
              aria-label={message.feedback === "down" ? "Remove rating" : "Bad answer"}
              aria-pressed={message.feedback === "down"}
              onClick={handleThumbsDown}
            >
              <ThumbsDown
                className="size-4"
                strokeWidth={1.5}
                fill={message.feedback === "down" ? "currentColor" : "none"}
                aria-hidden="true"
              />
            </Button>
          </>
        )}
        {showBudget && <BudgetMeter messageId={message.id} />}
      </div>
      <p role="status" className="text-footnote text-danger empty:hidden">
        {message.actionError ?? ""}
      </p>
      {showCommentBox && (
        <label className="block">
          <span className="sr-only">What went wrong? (optional)</span>
          <input
            autoFocus
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                submitComment();
              }
              if (event.key === "Escape") {
                event.preventDefault();
                setComment("");
                setShowCommentBox(false);
              }
            }}
            onBlur={submitComment}
            placeholder="What went wrong? (optional)"
            className="hit-target w-full max-w-sm rounded-md border border-separator bg-bg-tertiary px-3 text-body text-label placeholder:text-label-tertiary"
          />
        </label>
      )}
    </div>
  );
}

/**
 * How much of the hard token budget this answer's compiled context spent: a
 * thin meter and the two numbers. Read from the persisted bundle (the same
 * query the inspector's Bundle view uses, so opening it costs nothing more);
 * an answer with no bundle shows nothing.
 */
function BudgetMeter({ messageId }: { messageId: string }) {
  const bundle = useQuery({
    queryKey: contextBundleQueryKey(messageId),
    queryFn: ({ signal }) => fetchContextBundle(messageId, signal),
    enabled: !messageId.startsWith("pending-"),
    retry: false,
  });
  if (bundle.data === undefined || bundle.data === null) return null;
  const { tokens_consumed: spent, token_budget: budget } = bundle.data;
  const percent = Math.min(100, Math.round((spent / budget) * 100));
  return (
    <span className="ml-auto flex items-center gap-2 pl-2 text-caption text-label-secondary">
      <span
        role="meter"
        aria-label="Context budget used"
        aria-valuemin={0}
        aria-valuemax={budget}
        aria-valuenow={spent}
        aria-valuetext={`${spent} of ${budget} tokens`}
        className="h-0.5 w-16 overflow-hidden rounded-full bg-fill"
      >
        <span className="block h-full bg-accent" style={{ width: `${percent}%` }} />
      </span>
      <span className="font-mono" aria-hidden="true">
        {spent}/{budget} tokens
      </span>
    </span>
  );
}

function ToolCallPanel({ result }: { result: ToolResult }) {
  const deniedSource = result.offending_source;
  return (
    <section
      className="measure-reading flex flex-col gap-2 border-l-2 border-separator pl-4"
      aria-label="Tool call state"
    >
      <p className="font-mono text-caption uppercase tracking-caps text-label-secondary">
        Tool call · {result.status.replace("_", " ")}
      </p>
      {result.status === "pending_approval" && (
        <p className="text-callout text-label">
          This call is recorded and has not run.{" "}
          <Link className="font-semibold text-accent underline-offset-2 hover:underline" href="/tools">
            Review it in Tools.
          </Link>
        </p>
      )}
      {result.status === "succeeded" && (
        <pre className="overflow-x-auto font-mono text-footnote text-label">
          {JSON.stringify(result.result, null, 2)}
        </pre>
      )}
      {result.status === "denied" && (
        <p className="text-callout text-danger">
          {deniedSource !== null
            ? `Retrieved source “${deniedSource}” did not have enough authority.`
            : `Denied: ${result.denied_reason ?? "policy"}.`}
        </p>
      )}
      {result.status === "failed" && (
        <p className="text-callout text-danger">Failed: {result.error_code ?? "unknown_error"}</p>
      )}
    </section>
  );
}

function citationsIn(paragraph: string, citations: Citation[]): Citation[] {
  const markers = new Set([...paragraph.matchAll(/\[(\d+)\]/g)].map((match) => Number(match[1])));
  return citations
    .filter((citation) => markers.has(citation.marker))
    .sort((left, right) => left.marker - right.marker);
}

function titleFor(citation: Citation, titles?: ReadonlyMap<string, string>): string {
  const title = citation.document_id === null ? undefined : titles?.get(citation.document_id);
  return title === undefined ? "Document" : title.replace(/\.(pdf|md|txt|docx?|html?)$/i, "");
}

function noteId(messageId: string, marker: number): string {
  return `source-${messageId}-${marker}`;
}

function flowLabel(flow: string): string {
  if (flow === "rag") return "Documents";
  if (flow === "nl2sql") return "Data";
  if (flow === "tool") return "Tool";
  return "Chat";
}

function flowSource(flow: string): string {
  if (flow === "rag") return "your documents";
  if (flow === "nl2sql") return "the data warehouse, through read-only SQL";
  if (flow === "tool") return "a registered tool";
  return "the model alone, with no documents or data";
}

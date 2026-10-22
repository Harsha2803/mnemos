"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDown, BookOpenText } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { EmptyState } from "@/components/ui/EmptyState";
import { fetchDocuments, KNOWLEDGE_QUERY_KEY, type Citation } from "@/lib/knowledge/api";

import { MessageBubble, type DisplayMessage } from "./MessageBubble";

export type MessageListProps = {
  messages: DisplayMessage[];
  onCitationClick?: (citation: Citation) => void;
  onMessageSelect?: (message: DisplayMessage) => void;
  onToggleBookmark?: (message: DisplayMessage) => void;
  onRate?: (message: DisplayMessage, rating: "up" | "down" | null, comment?: string) => void;
  /** Ask again, for an answer that failed: given the failed answer. */
  onRetry?: (message: DisplayMessage) => void;
  selectedCitationId?: string;
};

/** Below this transcript width there is no room for a margin of sources. */
const WIDE_TRANSCRIPT_PX = 736; // 46rem, the container query in MessageBubble
/** "At the bottom" has a little give, so a reader a line short still follows. */
const FOLLOW_SLACK_PX = 120;

/**
 * The conversation as a document, and how it scrolls.
 *
 * **The reader's place is theirs.** While they are at the end, new text keeps
 * the view at the end. Once they scroll up to reread, nothing moves: new text
 * arrives below and a "Jump to latest" control appears instead of yanking them
 * down. Reaching the end again, by scrolling or by that control, resumes
 * following.
 *
 * **One announcement, at the end.** Streaming text is `aria-busy` while it
 * fills, and a single polite live region says when the answer is complete (or
 * stopped, or failed) — rather than a screen reader reading every token.
 */
export function MessageList({
  messages,
  onCitationClick,
  onMessageSelect,
  onToggleBookmark,
  onRate,
  onRetry,
  selectedCitationId,
}: MessageListProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const followTail = useRef(true);
  const [behind, setBehind] = useState(false);
  const [wide, setWide] = useState(true);
  const [announcement, setAnnouncement] = useState("");
  const wasStreaming = useRef<Set<string>>(new Set());

  const documents = useQuery({
    queryKey: KNOWLEDGE_QUERY_KEY,
    queryFn: ({ signal }) => fetchDocuments(signal),
    enabled: messages.some((message) => (message.citations?.length ?? 0) > 0),
  });
  const documentTitles = useMemo(
    () =>
      new Map(
        (Array.isArray(documents.data) ? documents.data : []).map((document) => [document.id, document.title]),
      ),
    [documents.data],
  );

  // The scroll pane is the page's, not this list's: the nearest scrolling
  // ancestor. Found once, then watched.
  useEffect(() => {
    const pane = scrollParent(rootRef.current);
    if (pane === null) return;
    const onScroll = () => {
      followTail.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < FOLLOW_SLACK_PX;
      if (followTail.current) setBehind(false);
    };
    onScroll();
    pane.addEventListener("scroll", onScroll, { passive: true });
    return () => pane.removeEventListener("scroll", onScroll);
  }, []);

  // Width decides how a source numeral behaves (margin vs inline), so it is
  // measured here once for every answer rather than per paragraph.
  useLayoutEffect(() => {
    const element = rootRef.current;
    if (element === null || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWide(entry.contentRect.width >= WIDE_TRANSCRIPT_PX);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // What is at the end of the conversation. Only a change *there* (a new turn,
  // more streamed text) moves the view or raises "Jump to latest"; a bookmark
  // toggled further up changes `messages` too and must do neither.
  const last = messages.at(-1);
  const tail = last === undefined ? "" : `${messages.length}:${last.id}:${last.content.length}`;
  useEffect(() => {
    if (tail === "") return;
    // jsdom has no layout, so `scrollIntoView` does not exist there.
    if (followTail.current) bottomRef.current?.scrollIntoView?.({ block: "end" });
    else setBehind(true);
  }, [tail]);

  useEffect(() => {
    const streamingNow = new Set(messages.filter((m) => m.streaming === true).map((m) => m.id));
    if (streamingNow.size > 0 && wasStreaming.current.size === 0) setAnnouncement("Mnemos is answering.");
    if (streamingNow.size === 0 && wasStreaming.current.size > 0) {
      const last = messages.at(-1);
      setAnnouncement(
        last?.failed === true
          ? "The answer could not be completed."
          : last?.content.endsWith("Generation stopped.") === true
            ? "Generation stopped."
            : "Answer complete.",
      );
    }
    wasStreaming.current = streamingNow;
  }, [messages]);

  function jumpToLatest(): void {
    followTail.current = true;
    setBehind(false);
    bottomRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }

  const lastAnswerId = [...messages].reverse().find((m) => m.role === "assistant")?.id;

  return (
    <div ref={rootRef} className="@container/transcript flex min-h-full min-w-0 flex-col">
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
      {messages.length === 0 ? (
        <EmptyState
          icon={BookOpenText}
          title="A blank page"
          description="Ask about a policy, a number in your data, or anything else. Mnemos chooses where to look, and every answer shows its sources."
        />
      ) : (
        <div className="flex min-w-0 flex-col gap-6 px-4 pb-8 pt-2 sm:px-6 [&>*:first-child_.border-t]:border-t-0 [&>*:first-child_.border-t]:pt-4">
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              wide={wide}
              documentTitles={documentTitles}
              showBudget={message.id === lastAnswerId}
              onCitationClick={onCitationClick}
              onMessageSelect={message.role === "assistant" ? () => onMessageSelect?.(message) : undefined}
              onToggleBookmark={message.role === "assistant" ? () => onToggleBookmark?.(message) : undefined}
              onRate={
                message.role === "assistant"
                  ? (rating, comment) => onRate?.(message, rating, comment)
                  : undefined
              }
              onRetry={message.role === "assistant" && onRetry ? () => onRetry(message) : undefined}
              selectedCitationId={selectedCitationId}
            />
          ))}
        </div>
      )}
      <div ref={bottomRef} />
      {behind && (
        <div className="pointer-events-none sticky bottom-3 mt-auto flex justify-center">
          <button
            type="button"
            onClick={jumpToLatest}
            className={[
              "hit-target pointer-events-auto inline-flex items-center gap-2 rounded-full border border-separator",
              "bg-bg-tertiary px-4 text-footnote font-semibold text-label shadow-md animate-fade-in-up",
              "transition-colors duration-150 ease-standard hover:bg-fill-secondary",
            ].join(" ")}
          >
            <ArrowDown className="size-4" strokeWidth={1.5} aria-hidden="true" />
            Jump to latest
          </button>
        </div>
      )}
    </div>
  );
}

function scrollParent(element: HTMLElement | null): HTMLElement | null {
  let current = element?.parentElement ?? null;
  while (current !== null) {
    const { overflowY } = window.getComputedStyle(current);
    if (overflowY === "auto" || overflowY === "scroll") return current;
    current = current.parentElement;
  }
  return null;
}

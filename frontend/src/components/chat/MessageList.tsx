import { MessageCircle } from "lucide-react";
import { useEffect, useRef } from "react";

import { EmptyState } from "@/components/ui/EmptyState";

import type { Citation } from "@/lib/knowledge/api";

import { MessageBubble, type DisplayMessage } from "./MessageBubble";

/**
 * The assistant bubble appears immediately, at zero content, and fills as
 * tokens arrive — never a spinner over a blank region (DesignSystem §4). The
 * list scrolls itself to the newest turn on every change, which is what makes
 * that filling visible without the user reaching for the scrollbar.
 */
export type MessageListProps = {
  messages: DisplayMessage[];
  onCitationClick?: (citation: Citation) => void;
  onMessageSelect?: (message: DisplayMessage) => void;
  onToggleBookmark?: (message: DisplayMessage) => void;
  onRate?: (message: DisplayMessage, rating: "up" | "down" | null, comment?: string) => void;
  selectedCitationId?: string;
};

export function MessageList({
  messages,
  onCitationClick,
  onMessageSelect,
  onToggleBookmark,
  onRate,
  selectedCitationId,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const followTail = useRef(true);

  useEffect(() => {
    const scrollPane = bottomRef.current?.parentElement?.parentElement;
    if (!scrollPane) return;
    const onScroll = () => {
      followTail.current = scrollPane.scrollHeight - scrollPane.scrollTop - scrollPane.clientHeight < 120;
    };
    onScroll();
    scrollPane.addEventListener("scroll", onScroll, { passive: true });
    return () => scrollPane.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    // jsdom has no layout, so `scrollIntoView` does not exist there — guarded
    // rather than polyfilled, since the test suite has no scroll position to
    // assert on in the first place (DesignSystem's `harness.ts` note in
    // vitest.setup.ts covers the same gap for other layout APIs).
    if (followTail.current) bottomRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <EmptyState
        icon={MessageCircle}
        title="Nothing here yet"
        description="Ask a question below to start the conversation."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6 px-4 py-6">
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          onCitationClick={onCitationClick}
          onMessageSelect={message.role === "assistant" ? () => onMessageSelect?.(message) : undefined}
          onToggleBookmark={
            message.role === "assistant" ? () => onToggleBookmark?.(message) : undefined
          }
          onRate={
            message.role === "assistant"
              ? (rating, comment) => onRate?.(message, rating, comment)
              : undefined
          }
          selectedCitationId={selectedCitationId}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

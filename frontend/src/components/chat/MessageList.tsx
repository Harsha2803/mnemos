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
};

export function MessageList({ messages, onCitationClick }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // jsdom has no layout, so `scrollIntoView` does not exist there — guarded
    // rather than polyfilled, since the test suite has no scroll position to
    // assert on in the first place (DesignSystem's `harness.ts` note in
    // vitest.setup.ts covers the same gap for other layout APIs).
    bottomRef.current?.scrollIntoView?.({ block: "end" });
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
        />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}

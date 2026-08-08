"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { CHAT_SESSIONS_QUERY_KEY } from "@/components/chat/ChatSessionList";
import { Composer } from "@/components/chat/Composer";
import type { DisplayMessage } from "@/components/chat/MessageBubble";
import { MessageList } from "@/components/chat/MessageList";
import { Skeleton } from "@/components/ui/Skeleton";
import { fetchSession } from "@/lib/chat/api";
import { streamChatReply } from "@/lib/chat/stream";

function sessionQueryKey(sessionId: string) {
  return ["chat", "session", sessionId] as const;
}

/**
 * One conversation: the message list and the composer.
 *
 * Messages start from `GET /v1/chat/sessions/{id}` and, from that point on,
 * are owned by local state — a background refetch of the same query must not
 * clobber a reply that is still streaming in, so the server response only
 * seeds state once per session id (`loadedFor`) rather than on every render.
 */
export default function ChatSessionPage() {
  const params = useParams<{ sessionId: string }>();
  const sessionId = params.sessionId;
  const queryClient = useQueryClient();

  const { data, isPending } = useQuery({
    queryKey: sessionQueryKey(sessionId),
    queryFn: ({ signal }) => fetchSession(sessionId, signal),
  });

  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const loadedFor = useRef<string | null>(null);

  useEffect(() => {
    if (data === undefined || loadedFor.current === sessionId) return;
    loadedFor.current = sessionId;
    setMessages(
      data.messages.map((message) => ({
        id: message.id,
        role: message.role === "user" ? "user" : "assistant",
        content: message.content,
      })),
    );
  }, [data, sessionId]);

  // Abandon an in-flight stream when the user navigates to a different
  // session, so tokens for a conversation nobody is looking at do not keep
  // arriving and do not leave the composer stuck disabled.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, [sessionId]);

  function handleSend(content: string): void {
    const userMessageId = `pending-user-${crypto.randomUUID()}`;
    const assistantMessageId = `pending-assistant-${crypto.randomUUID()}`;

    setMessages((prev) => [
      ...prev,
      { id: userMessageId, role: "user", content },
      { id: assistantMessageId, role: "assistant", content: "", streaming: true },
    ]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    void streamChatReply(
      sessionId,
      content,
      {
        onToken: (text) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId ? { ...m, content: m.content + text } : m,
            ),
          );
        },
        onDone: (message) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? { id: message.id, role: "assistant", content: message.content }
                : m,
            ),
          );
          setStreaming(false);
          void queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
        },
        onError: (message) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? {
                    ...m,
                    content: m.content.length > 0 ? m.content : message,
                    streaming: false,
                  }
                : m,
            ),
          );
          setStreaming(false);
        },
      },
      controller.signal,
    );
  }

  function handleStop(): void {
    abortRef.current?.abort();
    setStreaming(false);
  }

  return (
    <div className="-mx-6 -my-8 flex h-[calc(100dvh-3.5rem)] flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        {isPending ? (
          <div className="flex flex-col gap-4 px-4 py-6" aria-hidden="true">
            <Skeleton className="ml-auto h-16 w-2/3" />
            <Skeleton className="h-24 w-3/4" />
            <Skeleton className="ml-auto h-12 w-1/2" />
          </div>
        ) : (
          <MessageList messages={messages} />
        )}
      </div>
      <Composer onSend={handleSend} onStop={handleStop} streaming={streaming} />
    </div>
  );
}

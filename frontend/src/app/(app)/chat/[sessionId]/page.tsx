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
import { useInspectorSelection } from "@/lib/inspector/SelectionProvider";
import type { Citation } from "@/lib/knowledge/api";

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
  const { select, selection } = useInspectorSelection();

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
    const citations = data.citations ?? [];
    setMessages(
      data.messages.map((message) => ({
        id: message.id,
        role: message.role === "user" ? "user" : "assistant",
        content: message.content,
        flow: message.flow,
        routeReason: message.router_rationale,
        citations: citations.filter((c) => c.message_id === message.id),
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
      { id: userMessageId, role: "user", content, justSent: true },
      { id: assistantMessageId, role: "assistant", content: "", streaming: true },
    ]);
    setStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    void streamChatReply(
      sessionId,
      content,
      {
        onRoute: ({ flow, reason }) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId ? { ...m, flow, routeReason: reason } : m,
            ),
          );
        },
        onToken: (text) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId ? { ...m, content: m.content + text } : m,
            ),
          );
        },
        onDone: (message, nl2sql) => {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantMessageId
                ? {
                    id: message.id,
                    role: "assistant",
                    content: message.content,
                    flow: message.flow,
                    routeReason: message.router_rationale,
                    nl2sql,
                  }
                : m,
            ),
          );
          setStreaming(false);
          void queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
          // Citations are written server-side after the stream completes, so
          // they are not in the `done` frame — refetch the session to pick
          // them up, and let the effect above re-seed only if this is a
          // different session (it is not, so state is preserved).
          void queryClient
            .invalidateQueries({ queryKey: sessionQueryKey(sessionId) })
            .then(async () => {
              const refreshed = await queryClient.fetchQuery({
                queryKey: sessionQueryKey(sessionId),
                queryFn: ({ signal }) => fetchSession(sessionId, signal),
              });
              const forMessage = (refreshed.citations ?? []).filter(
                (c) => c.message_id === message.id,
              );
              if (forMessage.length > 0) {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === message.id ? { ...m, citations: forMessage } : m,
                  ),
                );
              }
            });
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
    setMessages((current) =>
      current.map((message) =>
        message.streaming === true
          ? {
              ...message,
              content:
                message.content.length > 0
                  ? `${message.content}\n\nGeneration stopped.`
                  : "Generation stopped.",
              streaming: false,
            }
          : message,
      ),
    );
    setStreaming(false);
  }

  function handleCitationClick(citation: Citation): void {
    const message = messages.find((item) => item.id === citation.message_id);
    if (!message) return;
    select({
      kind: "citation",
      message: {
        id: message.id,
        content: message.content,
        citations: message.citations ?? [],
        nl2sql: message.nl2sql,
      },
      citation,
    });
  }

  function handleMessageSelect(message: DisplayMessage): void {
    select({
      kind: "message",
      message: {
        id: message.id,
        content: message.content,
        citations: message.citations ?? [],
        nl2sql: message.nl2sql,
      },
    });
  }

  return (
    <div className="-mx-4 -my-4 flex h-[calc(100dvh-3.5rem)] flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto scrollbar-thin">
        {isPending ? (
          <div className="flex flex-col gap-4 px-4 py-6" aria-hidden="true">
            <Skeleton className="ml-auto h-16 w-2/3" />
            <Skeleton className="h-24 w-3/4" />
            <Skeleton className="ml-auto h-12 w-1/2" />
          </div>
        ) : (
          <MessageList
            messages={messages}
            onCitationClick={handleCitationClick}
            onMessageSelect={handleMessageSelect}
            selectedCitationId={selection?.kind === "citation" ? selection.citation.id : undefined}
          />
        )}
      </div>
      <Composer
        onSend={handleSend}
        onStop={handleStop}
        streaming={streaming}
      />
    </div>
  );
}

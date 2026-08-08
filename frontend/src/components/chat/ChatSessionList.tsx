"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Plus } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { List, ListItem } from "@/components/ui/List";
import { Skeleton } from "@/components/ui/Skeleton";
import { createSession, fetchSessions } from "@/lib/chat/api";

export const CHAT_SESSIONS_QUERY_KEY = ["chat", "sessions"] as const;

/**
 * The sidebar's session list, above the account footer (TRACKER §5
 * deliverable 5). A new user sees an `EmptyState` with the one action that
 * matters; everyone else sees their conversations, newest first, with the
 * current one marked by `aria-current` rather than colour alone.
 */
export function ChatSessionList() {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data, isPending } = useQuery({
    queryKey: CHAT_SESSIONS_QUERY_KEY,
    queryFn: ({ signal }) => fetchSessions(signal),
  });

  async function startNewChat(): Promise<void> {
    const session = await createSession();
    await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
    router.push(`/chat/${session.id}`);
  }

  if (isPending) {
    return (
      <div className="flex flex-col gap-2 px-2" aria-hidden="true">
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-full" />
        <Skeleton className="h-9 w-3/4" />
      </div>
    );
  }

  const sessions = data?.sessions ?? [];

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between px-2">
        <span className="text-footnote font-semibold text-label-secondary">Conversations</span>
        <Button rank="plain" aria-label="New chat" onClick={() => void startNewChat()}>
          <Plus className="size-4" strokeWidth={1.5} aria-hidden="true" />
        </Button>
      </div>

      {sessions.length === 0 ? (
        <EmptyState
          icon={MessageCircle}
          title="No conversations yet"
          headingLevel={3}
          action={
            <Button rank="tinted" onClick={() => void startNewChat()}>
              New chat
            </Button>
          }
        />
      ) : (
        <List label="Conversations">
          {sessions.map((session) => (
            <ListItem
              key={session.id}
              href={`/chat/${session.id}`}
              current={pathname === `/chat/${session.id}`}
            >
              {session.title}
            </ListItem>
          ))}
        </List>
      )}
    </div>
  );
}

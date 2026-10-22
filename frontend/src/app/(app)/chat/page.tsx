"use client";

import { useQueryClient } from "@tanstack/react-query";
import { MessageCircle } from "lucide-react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { CHAT_SESSIONS_QUERY_KEY } from "@/components/chat/ChatSessionList";
import { createSession } from "@/lib/chat/api";

/** `/chat` with nothing selected — a new user's landing state. */
export default function ChatIndexPage() {
  const router = useRouter();
  const queryClient = useQueryClient();

  async function startNewChat(): Promise<void> {
    const session = await createSession();
    await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
    router.push(`/chat/${session.id}`);
  }

  return (
    <EmptyState
      icon={MessageCircle}
      title="Start a conversation"
      description="Ask about a policy, a figure in your data, or anything else. Mnemos chooses where to look, and every answer shows where it came from."
      action={
        <Button rank="filled" onClick={() => void startNewChat()}>
          New chat
        </Button>
      }
    />
  );
}

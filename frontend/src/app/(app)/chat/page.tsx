"use client";

import { MessageCircle } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { useStartNewChat } from "@/lib/chat/useStartNewChat";

/** `/chat` with nothing selected — a new user's landing state. */
export default function ChatIndexPage() {
  const startNewChat = useStartNewChat();

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

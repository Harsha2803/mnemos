"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { createSession } from "./api";

/** The session list's query key, shared by everything that reads or refreshes it. */
export const CHAT_SESSIONS_QUERY_KEY = ["chat", "sessions"] as const;

/**
 * Create a conversation and open it. One implementation for every way in —
 * the sidebar's New, the empty chat page, the `n` shortcut and the command
 * palette — so they cannot drift into creating sessions differently.
 */
export function useStartNewChat(): () => Promise<void> {
  const router = useRouter();
  const queryClient = useQueryClient();
  return useCallback(async () => {
    const session = await createSession();
    await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
    router.push(`/chat/${session.id}`);
  }, [queryClient, router]);
}

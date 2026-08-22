"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark as BookmarkIcon, Trash2 } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  CHAT_BOOKMARKS_QUERY_KEY,
  fetchBookmarks,
  removeBookmark,
  type BookmarkedMessage,
} from "@/lib/chat/api";

/**
 * Every message bookmarked from anywhere in the app, newest first — the
 * Tool-console list-screen pattern (header, one query-driven section,
 * skeleton/empty/error states), since this is naturally a flat list across
 * many sessions rather than something that belongs inside one conversation
 * (TRACKER §5 deliverable 2).
 */
export default function BookmarksPage() {
  const queryClient = useQueryClient();
  const { data, isPending } = useQuery({
    queryKey: CHAT_BOOKMARKS_QUERY_KEY,
    queryFn: ({ signal }) => fetchBookmarks(signal),
  });

  async function handleRemove(messageId: string): Promise<void> {
    await removeBookmark(messageId);
    await queryClient.invalidateQueries({ queryKey: CHAT_BOOKMARKS_QUERY_KEY });
  }

  const bookmarks = data?.bookmarks ?? [];

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2">
        <h1 className="text-large-title font-semibold tracking-title text-label">Bookmarks</h1>
        <p className="text-callout leading-relaxed text-label-secondary">
          Messages you saved from any conversation, with the note you left on each one.
        </p>
      </header>

      <section className="flex flex-col gap-3" aria-labelledby="bookmarks-heading">
        <h2 id="bookmarks-heading" className="sr-only">
          Saved messages
        </h2>
        {isPending ? (
          <div className="flex flex-col gap-2" aria-hidden="true">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : bookmarks.length === 0 ? (
          <EmptyState
            icon={BookmarkIcon}
            title="No bookmarks yet"
            description="Bookmark an answer from any conversation and it will show up here."
            headingLevel={3}
          />
        ) : (
          <div className="list-group">
            {bookmarks.map((item) => (
              <BookmarkRow key={item.id} item={item} onRemove={() => void handleRemove(item.message_id)} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function BookmarkRow({ item, onRemove }: { item: BookmarkedMessage; onRemove: () => void }) {
  return (
    <div className="list-row flex flex-col gap-2 px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <Link
          href={`/chat/${item.session_id}#message-${item.message_id}`}
          className="min-w-0 text-callout font-semibold text-accent hover:underline"
        >
          {item.session_title}
        </Link>
        <Button
          rank="plain"
          aria-label={`Remove bookmark on message in ${item.session_title}`}
          onClick={onRemove}
        >
          <Trash2 className="size-4" strokeWidth={1.5} aria-hidden="true" />
        </Button>
      </div>
      <p className="line-clamp-3 text-body leading-relaxed text-label">{item.message_content}</p>
      {item.note !== null && item.note.length > 0 && (
        <p className="text-footnote text-label-secondary">
          <span className="font-semibold">Note:</span> {item.note}
        </p>
      )}
    </div>
  );
}

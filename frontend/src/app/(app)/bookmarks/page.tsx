"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark as BookmarkIcon, Trash2 } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
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
      <PageHeader
        title="Bookmarks"
        description="Answers you kept, from any conversation, with the note you left on each."
      />

      <section className="flex flex-col gap-3" aria-labelledby="bookmarks-heading">
        <h2 id="bookmarks-heading" className="sr-only">
          Saved messages
        </h2>
        {isPending ? (
          <div className="flex flex-col gap-2" role="status" aria-label="Loading bookmarks">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        ) : bookmarks.length === 0 ? (
          <EmptyState
            icon={BookmarkIcon}
            title="No bookmarks yet"
            description="Press Bookmark under any answer to keep it here, with its conversation one click away."
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
    <div className="list-row flex flex-col gap-2 py-4">
      <div className="flex items-start justify-between gap-3">
        <Link
          href={`/chat/${item.session_id}#message-${item.message_id}`}
          className="hit-target inline-flex min-w-0 items-center text-callout font-semibold text-accent underline-offset-4 hover:underline"
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
      <p className="measure-reading line-clamp-3 font-serif text-reading leading-relaxed text-label">{item.message_content}</p>
      {item.note !== null && item.note.length > 0 && (
        <p className="border-l-2 border-rubric pl-3 text-footnote text-label-secondary">
          <span className="font-mono uppercase tracking-caps">Note </span>
          {item.note}
        </p>
      )}
    </div>
  );
}

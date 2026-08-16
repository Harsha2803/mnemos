"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { MessageCircle, Pencil, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { List } from "@/components/ui/List";
import { MarqueeText } from "@/components/ui/MarqueeText";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  createSession,
  deleteSession,
  fetchSessions,
  renameSession,
  type ChatSession,
} from "@/lib/chat/api";

export const CHAT_SESSIONS_QUERY_KEY = ["chat", "sessions"] as const;

/**
 * The sidebar's session list, above the account footer (TRACKER §5
 * deliverable 5). A new user sees an `EmptyState` with the one action that
 * matters; everyone else sees their conversations, newest first, with the
 * current one marked by `aria-current` rather than colour alone. Each row is
 * named for what it is about — the backend titles a session from its first
 * message the moment it is sent — and carries its own rename and delete
 * controls, always visible rather than hover-only (DocumentList's delete
 * button sets this precedent: a control only a mouse can find is a control a
 * touch or keyboard user cannot).
 *
 * A row that navigates *and* carries actions cannot be `ListItem`'s
 * `href` form — that nests the action buttons inside the `<a>`, which is
 * invalid HTML and makes the trailing buttons un-clickable without also
 * navigating. The link and its actions are siblings here instead.
 */
export function ChatSessionList() {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data, isPending } = useQuery({
    queryKey: CHAT_SESSIONS_QUERY_KEY,
    queryFn: ({ signal }) => fetchSessions(signal),
  });

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ChatSession | null>(null);

  async function startNewChat(): Promise<void> {
    const session = await createSession();
    await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
    router.push(`/chat/${session.id}`);
  }

  function startRename(session: ChatSession): void {
    setRenameError(null);
    setEditingId(session.id);
    setEditingValue(session.title);
  }

  function cancelRename(): void {
    setEditingId(null);
    setEditingValue("");
  }

  async function commitRename(session: ChatSession): Promise<void> {
    const title = editingValue.trim();
    cancelRename();
    if (title.length === 0 || title === session.title) return;
    try {
      await renameSession(session.id, title);
      await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
    } catch (cause) {
      setRenameError(
        cause instanceof Error ? cause.message : "could not rename this conversation",
      );
    }
  }

  async function confirmDelete(): Promise<void> {
    const target = pendingDelete;
    if (target === null) return;
    setPendingDelete(null);
    await deleteSession(target.id);
    await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
    // The row that was just deleted may be the conversation on screen —
    // staying on `/chat/{deleted id}` would otherwise leave the composer
    // pointed at a session that no longer exists.
    if (pathname === `/chat/${target.id}`) router.push("/chat");
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

      {renameError !== null && (
        <p role="alert" className="px-2 text-footnote text-danger">
          {renameError}
        </p>
      )}

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
          {sessions.map((session) => {
            const href = `/chat/${session.id}`;
            const editing = editingId === session.id;
            return (
              <li key={session.id} className="list-row">
                <div className="flex w-full items-center">
                  {editing ? (
                    <RenameField
                      value={editingValue}
                      onChange={setEditingValue}
                      onCommit={() => void commitRename(session)}
                      onCancel={cancelRename}
                    />
                  ) : (
                    <Link
                      href={href}
                      aria-current={pathname === href ? "page" : undefined}
                      className="hit-target flex min-w-0 flex-1 items-center px-4 py-2 text-callout text-label transition-colors duration-150 ease-standard hover:bg-fill-tertiary aria-[current=page]:bg-fill-secondary aria-[current=page]:font-semibold"
                    >
                      <MarqueeText text={session.title} className="min-w-0 flex-1" />
                    </Link>
                  )}

                  {!editing && (
                    <div className="flex shrink-0 items-center gap-0.5 pr-1">
                      <Button
                        rank="plain"
                        aria-label={`Rename ${session.title}`}
                        onClick={() => startRename(session)}
                      >
                        <Pencil className="size-4" strokeWidth={1.5} aria-hidden="true" />
                      </Button>
                      <Button
                        rank="plain"
                        aria-label={`Delete ${session.title}`}
                        onClick={() => setPendingDelete(session)}
                      >
                        <Trash2 className="size-4" strokeWidth={1.5} aria-hidden="true" />
                      </Button>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </List>
      )}

      {/* DesignSystem §4: a destructive confirmation names the specific thing
          being destroyed, the same rule `DocumentList`'s delete dialog follows. */}
      <Dialog.Root
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay fixed inset-0 z-30 bg-label-quaternary" />
          <Dialog.Content className="dialog-content fixed left-1/2 top-1/2 z-40 w-[min(28rem,90vw)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-separator bg-bg p-6 shadow-lg">
            <Dialog.Title className="text-title-3 font-semibold tracking-title text-label">
              Delete “{pendingDelete?.title}”?
            </Dialog.Title>
            <Dialog.Description className="mt-2 text-callout leading-relaxed text-label-secondary">
              Its messages go with it. This cannot be undone.
            </Dialog.Description>
            <div className="mt-6 flex justify-end gap-2">
              <Dialog.Close asChild>
                <Button rank="plain">Cancel</Button>
              </Dialog.Close>
              <Button rank="filled" className="!bg-danger" onClick={() => void confirmDelete()}>
                Delete
              </Button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

type RenameFieldProps = {
  value: string;
  onChange: (value: string) => void;
  onCommit: () => void;
  onCancel: () => void;
};

/**
 * Enter and blur both commit, through the same path: Enter blurs the field
 * rather than committing directly, so there is exactly one place a rename is
 * sent. Escape sets a ref before it cancels, so the blur that follows (moving
 * focus away as the field unmounts) does not re-commit a value the user just
 * asked to discard.
 */
function RenameField({ value, onChange, onCommit, onCancel }: RenameFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const cancelledRef = useRef(false);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>): void {
    if (event.key === "Enter") {
      event.preventDefault();
      inputRef.current?.blur();
    } else if (event.key === "Escape") {
      event.preventDefault();
      cancelledRef.current = true;
      onCancel();
    }
  }

  function onBlur(): void {
    if (cancelledRef.current) return;
    onCommit();
  }

  return (
    <input
      ref={inputRef}
      value={value}
      aria-label="Conversation name"
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={onKeyDown}
      onBlur={onBlur}
      className="hit-target min-w-0 flex-1 rounded-md border border-accent bg-bg px-4 py-2 text-callout text-label"
    />
  );
}

"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderInput, FolderPlus, MessageCircle, Pencil, Plus, Search, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { List } from "@/components/ui/List";
import { MarqueeText } from "@/components/ui/MarqueeText";
import { Skeleton } from "@/components/ui/Skeleton";
import {
  CHAT_FOLDERS_QUERY_KEY,
  createFolder,
  createSession,
  deleteFolder,
  deleteSession,
  fetchFolders,
  fetchSessions,
  moveSessionToFolder,
  renameFolder,
  renameSession,
  type ChatSession,
  type Folder,
} from "@/lib/chat/api";

export const CHAT_SESSIONS_QUERY_KEY = ["chat", "sessions"] as const;

type PendingDelete =
  | { kind: "session"; session: ChatSession }
  | { kind: "folder"; folder: Folder };

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
 *
 * `C3` deliverable 1 adds folders: sessions group by folder first (each
 * folder always shown, even empty, so a just-created folder does not vanish
 * until something is filed into it), then the existing Today/Yesterday/
 * Previous 7 days/Older recency buckets cover whatever is left unfiled.
 */
export function ChatSessionList() {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data, isPending } = useQuery({
    queryKey: CHAT_SESSIONS_QUERY_KEY,
    queryFn: ({ signal }) => fetchSessions(signal),
  });
  const { data: folderData } = useQuery({
    queryKey: CHAT_FOLDERS_QUERY_KEY,
    queryFn: ({ signal }) => fetchFolders(signal),
  });

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const [query, setQuery] = useState("");
  const [movingId, setMovingId] = useState<string | null>(null);
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const [editingFolderId, setEditingFolderId] = useState<string | null>(null);
  const [editingFolderValue, setEditingFolderValue] = useState("");

  const sessions = useMemo(() => data?.sessions ?? [], [data?.sessions]);
  const folders = useMemo(() => folderData?.folders ?? [], [folderData?.folders]);
  const groups = useMemo(
    () => groupSessions(sessions, folders, query),
    [query, sessions, folders],
  );
  const anyVisible = groups.some((group) => group.sessions.length > 0);

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
      // No `folderId` argument: a rename must never silently un-file the
      // session (TRACKER §5 deliverable 1).
      await renameSession(session.id, title);
      await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
    } catch (cause) {
      setRenameError(
        cause instanceof Error ? cause.message : "could not rename this conversation",
      );
    }
  }

  async function moveSession(session: ChatSession, folderId: string): Promise<void> {
    setMovingId(null);
    const target = folderId === "" ? null : folderId;
    if (target === session.folder_id) return;
    await moveSessionToFolder(session.id, target);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY }),
      queryClient.invalidateQueries({ queryKey: CHAT_FOLDERS_QUERY_KEY }),
    ]);
  }

  function startNewFolder(): void {
    setCreatingFolder(true);
    setNewFolderName("");
  }

  function cancelNewFolder(): void {
    setCreatingFolder(false);
    setNewFolderName("");
  }

  async function commitNewFolder(): Promise<void> {
    const name = newFolderName.trim();
    cancelNewFolder();
    if (name.length === 0) return;
    await createFolder(name);
    await queryClient.invalidateQueries({ queryKey: CHAT_FOLDERS_QUERY_KEY });
  }

  function startRenameFolder(folder: Folder): void {
    setEditingFolderId(folder.id);
    setEditingFolderValue(folder.name);
  }

  function cancelRenameFolder(): void {
    setEditingFolderId(null);
    setEditingFolderValue("");
  }

  async function commitRenameFolder(folder: Folder): Promise<void> {
    const name = editingFolderValue.trim();
    cancelRenameFolder();
    if (name.length === 0 || name === folder.name) return;
    await renameFolder(folder.id, name);
    await queryClient.invalidateQueries({ queryKey: CHAT_FOLDERS_QUERY_KEY });
  }

  async function confirmDelete(): Promise<void> {
    const target = pendingDelete;
    if (target === null) return;
    setPendingDelete(null);
    if (target.kind === "session") {
      await deleteSession(target.session.id);
      await queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY });
      // The row that was just deleted may be the conversation on screen —
      // staying on `/chat/{deleted id}` would otherwise leave the composer
      // pointed at a session that no longer exists.
      if (pathname === `/chat/${target.session.id}`) router.push("/chat");
    } else {
      await deleteFolder(target.folder.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: CHAT_FOLDERS_QUERY_KEY }),
        queryClient.invalidateQueries({ queryKey: CHAT_SESSIONS_QUERY_KEY }),
      ]);
    }
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

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between px-2">
        <span className="text-footnote font-semibold text-label-secondary">Conversations</span>
        <div className="flex items-center gap-0.5">
          <Button rank="plain" aria-label="New folder" onClick={startNewFolder}>
            <FolderPlus className="size-4" strokeWidth={1.5} aria-hidden="true" />
          </Button>
          <Button rank="plain" aria-label="New chat" onClick={() => void startNewChat()}>
            <Plus className="size-4" strokeWidth={1.5} aria-hidden="true" />
          </Button>
        </div>
      </div>

      {renameError !== null && (
        <p role="alert" className="px-2 text-footnote text-danger">
          {renameError}
        </p>
      )}

      {(sessions.length > 0 || folders.length > 0) && (
        <label className="relative mx-1">
          <span className="sr-only">Search conversations</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-label-tertiary" aria-hidden="true" />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search conversations" className="hit-target w-full rounded-md border border-separator bg-bg pl-9 pr-3 text-footnote text-label" />
        </label>
      )}

      {sessions.length === 0 && folders.length === 0 && !creatingFolder ? (
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
          {creatingFolder && (
            <li key="new-folder" className="list-row px-1 py-1">
              <RenameField
                label="Folder name"
                value={newFolderName}
                onChange={setNewFolderName}
                onCommit={() => void commitNewFolder()}
                onCancel={cancelNewFolder}
              />
            </li>
          )}
          {groups.flatMap((group) => [
            <li key={`heading-${group.key}`} className="flex items-center justify-between gap-1 px-3 pb-1 pt-3">
              {group.kind === "folder" && editingFolderId === group.folder.id ? (
                <RenameField
                  label="Folder name"
                  value={editingFolderValue}
                  onChange={setEditingFolderValue}
                  onCommit={() => void commitRenameFolder(group.folder)}
                  onCancel={cancelRenameFolder}
                />
              ) : (
                <>
                  <span className="text-caption font-semibold uppercase tracking-wide text-label-tertiary">
                    {group.label}
                  </span>
                  {group.kind === "folder" && (
                    <div className="flex shrink-0 items-center gap-0.5">
                      <Button
                        rank="plain"
                        aria-label={`Rename ${group.folder.name}`}
                        onClick={() => startRenameFolder(group.folder)}
                      >
                        <Pencil className="size-3.5" strokeWidth={1.5} aria-hidden="true" />
                      </Button>
                      <Button
                        rank="plain"
                        aria-label={`Delete ${group.folder.name}`}
                        onClick={() => setPendingDelete({ kind: "folder", folder: group.folder })}
                      >
                        <Trash2 className="size-3.5" strokeWidth={1.5} aria-hidden="true" />
                      </Button>
                    </div>
                  )}
                </>
              )}
            </li>,
            ...(group.sessions.length === 0
              ? [
                  <li
                    key={`empty-${group.key}`}
                    className="px-3 pb-2 text-footnote text-label-tertiary"
                  >
                    No conversations here yet.
                  </li>,
                ]
              : group.sessions.map((session) => {
                  const href = `/chat/${session.id}`;
                  const editing = editingId === session.id;
                  const moving = movingId === session.id;
                  return (
                    <li key={session.id} className="list-row">
                      <div className="flex w-full items-center">
                        {editing ? (
                          <RenameField
                            label="Conversation name"
                            value={editingValue}
                            onChange={setEditingValue}
                            onCommit={() => void commitRename(session)}
                            onCancel={cancelRename}
                          />
                        ) : moving ? (
                          <label className="min-w-0 flex-1 px-4 py-2">
                            <span className="sr-only">Move “{session.title}” to a folder</span>
                            <select
                              autoFocus
                              defaultValue={session.folder_id ?? ""}
                              onChange={(event) => void moveSession(session, event.target.value)}
                              onBlur={() => setMovingId(null)}
                              className="hit-target w-full rounded-md border border-accent bg-bg px-2 text-callout text-label"
                            >
                              <option value="">No folder</option>
                              {folders.map((folder) => (
                                <option key={folder.id} value={folder.id}>
                                  {folder.name}
                                </option>
                              ))}
                            </select>
                          </label>
                        ) : (
                          <Link
                            href={href}
                            aria-current={pathname === href ? "page" : undefined}
                            className="hit-target flex min-w-0 flex-1 items-center px-4 py-2 text-callout text-label transition-colors duration-150 ease-standard hover:bg-fill-tertiary aria-[current=page]:bg-fill-secondary aria-[current=page]:font-semibold"
                          >
                            <MarqueeText text={session.title} className="min-w-0 flex-1" />
                          </Link>
                        )}

                        {!editing && !moving && (
                          <div className="flex shrink-0 items-center gap-0.5 pr-1">
                            {folders.length > 0 && (
                              <Button
                                rank="plain"
                                aria-label={`Move ${session.title} to a folder`}
                                onClick={() => setMovingId(session.id)}
                              >
                                <FolderInput className="size-4" strokeWidth={1.5} aria-hidden="true" />
                              </Button>
                            )}
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
                              onClick={() => setPendingDelete({ kind: "session", session })}
                            >
                              <Trash2 className="size-4" strokeWidth={1.5} aria-hidden="true" />
                            </Button>
                          </div>
                        )}
                      </div>
                    </li>
                  );
                })),
          ])}
          {query.trim() !== "" && !anyVisible && (
            <li className="px-3 py-4 text-footnote text-label-secondary">No conversations match.</li>
          )}
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
              Delete “{pendingDelete?.kind === "session" ? pendingDelete.session.title : pendingDelete?.folder.name}”?
            </Dialog.Title>
            <Dialog.Description className="mt-2 text-callout leading-relaxed text-label-secondary">
              {pendingDelete?.kind === "folder"
                ? "Its conversations are not deleted — they move back to unfiled."
                : "Its messages go with it. This cannot be undone."}
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

type SessionGroup =
  | { key: string; label: string; kind: "folder"; folder: Folder; sessions: ChatSession[] }
  | { key: string; label: string; kind: "recency"; sessions: ChatSession[] };

function groupSessions(sessions: ChatSession[], folders: Folder[], query: string): SessionGroup[] {
  const q = query.trim().toLocaleLowerCase();
  const filtered = sessions.filter((session) => session.title.toLocaleLowerCase().includes(q));

  const folderGroups: SessionGroup[] = folders
    .map((folder) => ({
      key: `folder-${folder.id}`,
      label: folder.name,
      kind: "folder" as const,
      folder,
      sessions: filtered.filter((session) => session.folder_id === folder.id),
    }))
    // A folder with no matches during an active search is noise; an empty
    // folder with no search active is still worth showing, so a
    // just-created folder does not disappear until something is filed in it.
    .filter((group) => q === "" || group.sessions.length > 0);

  const unfiled = filtered.filter((session) => session.folder_id === null);
  const recencyGroups = groupByRecency(unfiled).map((group) => ({
    key: `recency-${group.label}`,
    label: group.label,
    kind: "recency" as const,
    sessions: group.sessions,
  }));

  return [...folderGroups, ...recencyGroups];
}

type RecencyGroup = { label: string; sessions: ChatSession[] };

function groupByRecency(sessions: ChatSession[]): RecencyGroup[] {
  const now = new Date();
  const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const buckets = new Map<string, ChatSession[]>();
  for (const session of sessions) {
    const timestamp = new Date(session.last_message_at ?? session.updated_at).getTime();
    const ageDays = Math.floor((startToday - new Date(new Date(timestamp).getFullYear(), new Date(timestamp).getMonth(), new Date(timestamp).getDate()).getTime()) / 86_400_000);
    const label = ageDays <= 0 ? "Today" : ageDays === 1 ? "Yesterday" : ageDays <= 7 ? "Previous 7 days" : "Older";
    const bucket = buckets.get(label) ?? [];
    bucket.push(session);
    buckets.set(label, bucket);
  }
  return ["Today", "Yesterday", "Previous 7 days", "Older"].flatMap((label) => {
    const grouped = buckets.get(label);
    return grouped ? [{ label, sessions: grouped }] : [];
  });
}

type RenameFieldProps = {
  label: string;
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
 * asked to discard. Shared between session rename, folder rename, and new
 * folder creation — the only difference is the accessible `label`.
 */
function RenameField({ label, value, onChange, onCommit, onCancel }: RenameFieldProps) {
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
      aria-label={label}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={onKeyDown}
      onBlur={onBlur}
      className="hit-target min-w-0 flex-1 rounded-md border border-accent bg-bg px-4 py-2 text-callout text-label"
    />
  );
}

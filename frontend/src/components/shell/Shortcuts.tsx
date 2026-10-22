"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import { COMPOSER_INPUT_ID } from "@/components/chat/Composer";
import { CHAT_SESSIONS_QUERY_KEY, useStartNewChat } from "@/lib/chat/useStartNewChat";
import type { ChatSession } from "@/lib/chat/api";
import { useInspectorSelection } from "@/lib/inspector/SelectionProvider";
import { setPreference } from "@/lib/theme";

import { DESTINATIONS } from "./destinations";

/** Every shortcut, once: the handler and the help dialog both read this list. */
export const SHORTCUTS: readonly { keys: string[]; does: string }[] = [
  { keys: ["Ctrl", "K"], does: "Open the command palette (⌘K on a Mac)" },
  { keys: ["n"], does: "Start a new conversation" },
  { keys: ["/"], does: "Write in the composer" },
  { keys: ["["], does: "Previous source of the selected answer" },
  { keys: ["]"], does: "Next source of the selected answer" },
  { keys: ["i"], does: "Show or hide the context inspector" },
  { keys: ["Esc"], does: "Close a menu or dialog; with none open, clear the selection" },
  { keys: ["?"], does: "Show these shortcuts" },
];

/**
 * Keyboard shortcuts for the whole workspace, from one listener.
 *
 * Single keys act only when focus is not in a text field, so typing "n" into
 * the composer types an "n". Ctrl/⌘+K works everywhere. Escape is left to
 * whatever is open (Radix dialogs, popovers and sheets close themselves); only
 * when nothing is open does it clear the inspector's selection.
 */
export function Shortcuts({ onToggleInspector }: { onToggleInspector: () => void }) {
  const { selection, select } = useInspectorSelection();
  const startNewChat = useStartNewChat();
  const [helpOpen, setHelpOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent): void {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((open) => !open);
        return;
      }
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target) || document.querySelector("[role=dialog], [data-radix-popper-content-wrapper]")) {
        return;
      }

      const step = event.key === "]" ? 1 : event.key === "[" ? -1 : 0;
      if (step !== 0 && selection !== null) {
        const citations = [...selection.message.citations].sort((a, b) => a.marker - b.marker);
        if (citations.length === 0) return;
        const index = selection.kind === "citation" ? citations.findIndex((c) => c.id === selection.citation.id) : -1;
        const next = citations[index === -1 ? (step > 0 ? 0 : citations.length - 1) : index + step];
        if (next !== undefined) {
          event.preventDefault();
          select({ kind: "citation", message: selection.message, citation: next });
        }
        return;
      }

      switch (event.key) {
        case "n":
          event.preventDefault();
          void startNewChat();
          break;
        case "/": {
          const composer = document.getElementById(COMPOSER_INPUT_ID);
          if (composer !== null) {
            event.preventDefault();
            composer.focus();
          }
          break;
        }
        case "i":
          event.preventDefault();
          onToggleInspector();
          break;
        case "?":
          event.preventDefault();
          setHelpOpen(true);
          break;
        case "Escape":
          if (selection !== null) select(null);
          break;
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selection, select, startNewChat, onToggleInspector]);

  // The account menu offers the list too, for anyone who does not know "?".
  useEffect(() => {
    const open = () => setHelpOpen(true);
    window.addEventListener("mnemos:shortcuts", open);
    return () => window.removeEventListener("mnemos:shortcuts", open);
  }, []);

  return (
    <>
      <ShortcutsDialog open={helpOpen} onOpenChange={setHelpOpen} />
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onToggleInspector={onToggleInspector}
        onShowShortcuts={() => setHelpOpen(true)}
      />
    </>
  );
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

function Keys({ keys }: { keys: string[] }) {
  return (
    <span className="flex shrink-0 gap-1">
      {keys.map((key) => (
        <kbd
          key={key}
          className="min-w-6 rounded-sm border border-separator bg-bg-tertiary px-1.5 text-center font-mono text-caption text-label"
        >
          {key}
        </kbd>
      ))}
    </span>
  );
}

function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay fixed inset-0 z-30 bg-label-quaternary" />
        <Dialog.Content
          aria-describedby={undefined}
          className="dialog-content fixed left-1/2 top-1/2 z-40 w-[min(30rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-separator bg-bg-tertiary p-6 shadow-lg"
        >
          <Dialog.Title className="font-serif text-title-3 font-semibold text-label">Keyboard shortcuts</Dialog.Title>
          <p className="mt-1 text-footnote text-label-secondary">Single keys work when you are not typing in a field.</p>
          <dl className="mt-4 flex flex-col border-t border-separator">
            {SHORTCUTS.map(({ keys, does }) => (
              <div key={does} className="flex items-center justify-between gap-4 border-b border-separator py-2.5">
                <dt className="text-callout text-label">{does}</dt>
                <dd>
                  <Keys keys={keys} />
                </dd>
              </div>
            ))}
          </dl>
          <Dialog.Close className="hit-target mt-4 rounded-md px-4 text-callout font-semibold text-accent hover:bg-fill-tertiary">
            Done
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

type Command = { id: string; label: string; group: string; hint?: string; run: () => void };

/**
 * Ctrl/⌘+K: go anywhere or do anything by typing a few letters of it — every
 * section, the most recent conversations, a new chat, the inspector,
 * appearance. A combobox over a listbox (ARIA 1.2): focus stays in the input,
 * the arrow keys move the active option, Enter runs it.
 */
function CommandPalette({
  open,
  onOpenChange,
  onToggleInspector,
  onShowShortcuts,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onToggleInspector: () => void;
  onShowShortcuts: () => void;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const queryClient = useQueryClient();
  const startNewChat = useStartNewChat();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef<HTMLUListElement>(null);

  const commands = useMemo<Command[]>(() => {
    if (!open) return [];
    const sessions =
      queryClient.getQueryData<{ sessions: ChatSession[] }>(CHAT_SESSIONS_QUERY_KEY)?.sessions ?? [];
    return [
      { id: "new", label: "New conversation", group: "Do", hint: "n", run: () => void startNewChat() },
      { id: "inspector", label: "Show or hide the context inspector", group: "Do", hint: "i", run: onToggleInspector },
      { id: "shortcuts", label: "Keyboard shortcuts", group: "Do", hint: "?", run: onShowShortcuts },
      ...DESTINATIONS.filter((d) => d.href !== pathname).map((d) => ({
        id: `go-${d.href}`,
        label: `Go to ${d.label}`,
        group: "Go",
        run: () => router.push(d.href),
      })),
      ...sessions.slice(0, 8).map((session) => ({
        id: `chat-${session.id}`,
        label: session.title,
        group: "Conversations",
        run: () => router.push(`/chat/${session.id}`),
      })),
      ...(["system", "light", "dark"] as const).map((preference) => ({
        id: `theme-${preference}`,
        label: `Appearance: ${preference === "system" ? "match system" : preference}`,
        group: "Appearance",
        run: () => setPreference(preference),
      })),
    ];
  }, [open, queryClient, startNewChat, onToggleInspector, onShowShortcuts, pathname, router]);

  const visible = useMemo(() => {
    const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
    return commands.filter((command) => {
      const haystack = `${command.group} ${command.label}`.toLocaleLowerCase();
      return words.every((word) => haystack.includes(word));
    });
  }, [commands, query]);

  useEffect(() => {
    setActive(0);
  }, [query, open]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  useEffect(() => {
    listRef.current?.querySelector("[aria-selected=true]")?.scrollIntoView?.({ block: "nearest" });
  }, [active]);

  function run(command: Command | undefined): void {
    if (command === undefined) return;
    onOpenChange(false);
    command.run();
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLInputElement>): void {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => Math.min(index + 1, visible.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      run(visible[active]);
    }
  }

  const optionId = (index: number) => `${listId}-option-${index}`;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay fixed inset-0 z-30 bg-label-quaternary" />
        <Dialog.Content
          aria-describedby={undefined}
          className="palette-content fixed left-1/2 top-[12vh] z-40 flex max-h-[70vh] w-[min(36rem,calc(100vw-2rem))] -translate-x-1/2 flex-col overflow-hidden rounded-xl border border-separator bg-bg-tertiary shadow-lg"
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={onKeyDown}
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={visible.length > 0 ? optionId(active) : undefined}
            aria-autocomplete="list"
            aria-label="Go to or do"
            placeholder="Go to a section, a conversation, or do something…"
            className="hit-target w-full border-b border-separator bg-transparent px-5 py-3 text-body text-label placeholder:text-label-tertiary focus-visible:outline-none"
          />
          <ul ref={listRef} id={listId} role="listbox" aria-label="Commands" className="min-h-0 flex-1 overflow-y-auto py-2">
            {visible.length === 0 && (
              <li role="presentation" className="px-5 py-3 text-callout text-label-secondary">
                Nothing matches “{query}”.
              </li>
            )}
            {visible.map((command, index) => (
              <li
                key={command.id}
                id={optionId(index)}
                role="option"
                aria-selected={index === active}
                onMouseMove={() => setActive(index)}
                onClick={() => run(command)}
                className="flex min-h-11 cursor-pointer items-center gap-3 px-5 text-callout text-label aria-selected:bg-fill-secondary"
              >
                <span className="w-28 shrink-0 font-mono text-caption uppercase tracking-caps text-label-secondary">
                  {command.group}
                </span>
                <span className="min-w-0 flex-1 truncate">{command.label}</span>
                {command.hint !== undefined && <Keys keys={[command.hint]} />}
              </li>
            ))}
          </ul>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

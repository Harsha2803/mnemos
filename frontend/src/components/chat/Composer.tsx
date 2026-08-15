"use client";

import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { ArrowUp, Database, FileText, MessageSquare, Square, type LucideIcon } from "lucide-react";
import { useEffect, useRef, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";

export type ComposerProps = {
  onSend: (content: string) => void;
  onStop: () => void;
  streaming: boolean;
  useDocuments: boolean;
  onUseDocumentsChange: (value: boolean) => void;
  /** Answer by generating and running SQL against the datasource, rather than chat or RAG. */
  useDatasource: boolean;
  onUseDatasourceChange: (value: boolean) => void;
};

type Mode = "chat" | "documents" | "datasource";

type ModeOption = {
  value: Mode;
  label: string;
  Icon: LucideIcon;
};

/**
 * "Chat" is offered first and named, the same reasoning `ThemeToggle`'s
 * "Match system" option gives: it is the default, and a user who wants to go
 * back to it needs somewhere to click, not an absence of a choice.
 */
const MODE_OPTIONS: readonly ModeOption[] = [
  { value: "chat", label: "Chat", Icon: MessageSquare },
  { value: "documents", label: "Use documents", Icon: FileText },
  { value: "datasource", label: "Ask your data", Icon: Database },
];

function modeFor(useDocuments: boolean, useDatasource: boolean): Mode {
  if (useDatasource) return "datasource";
  if (useDocuments) return "documents";
  return "chat";
}

/**
 * A textarea that grows with its content, up to a cap — DesignSystem §4's
 * loading rule extends naturally here: the composer should not itself jump
 * around while somebody is mid-sentence.
 *
 * Enter sends; Shift+Enter inserts a newline. Disabled while a response
 * streams, with a visible stop control in its place (TRACKER §5 deliverable 5).
 *
 * The three answer modes are one Radix `ToggleGroup` (single-select,
 * `radiogroup` semantics from a component that already has roving focus and
 * ARIA right — the same primitive `ThemeToggle` uses for Appearance), not two
 * independent checkboxes with mutual exclusion bolted on: "chat" is a real,
 * nameable third state, and a `radiogroup` is what a mutually exclusive
 * choice among three options *is*, semantically. `useDocuments`/
 * `useDatasource` stay the props this component is driven by and reports
 * through — only the on-screen control changed shape.
 */
export function Composer({
  onSend,
  onStop,
  streaming,
  useDocuments,
  onUseDocumentsChange,
  useDatasource,
  onUseDatasourceChange,
}: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);
  const mode = modeFor(useDocuments, useDatasource);

  useEffect(() => {
    const el = ref.current;
    if (el === null) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 240)}px`;
  });

  function submit(): void {
    const el = ref.current;
    if (el === null || streaming) return;
    const content = el.value.trim();
    if (content.length === 0) return;
    onSend(content);
    el.value = "";
    el.style.height = "auto";
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  function onModeChange(next: string): void {
    // Radix emits "" when the pressed item is toggled off — a `radiogroup`
    // always has an answer, so an empty value means "no change", never "no
    // mode", the same reasoning `ThemeToggle` applies to Appearance.
    if (next === "") return;
    onUseDocumentsChange(next === "documents");
    onUseDatasourceChange(next === "datasource");
  }

  return (
    <div className="flex flex-col gap-2 border-t border-separator bg-bg px-4 py-3">
      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          rows={1}
          placeholder="Ask Mnemos anything"
          aria-label="Message"
          disabled={streaming}
          onKeyDown={onKeyDown}
          className={[
            "min-h-11 flex-1 resize-none rounded-md border border-separator bg-bg-secondary px-3 py-2",
            "text-body leading-normal text-label placeholder:text-label-tertiary",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2",
            "disabled:opacity-60",
          ].join(" ")}
        />
        {streaming ? (
          <Button
            rank="tinted"
            aria-label="Stop generating"
            onClick={onStop}
            className="!w-11 shrink-0 !px-0"
          >
            <Square className="size-4" strokeWidth={1.5} aria-hidden="true" />
          </Button>
        ) : (
          <Button
            rank="filled"
            aria-label="Send message"
            onClick={submit}
            className="!w-11 shrink-0 !rounded-full !px-0"
          >
            <ArrowUp className="size-[18px]" strokeWidth={2} aria-hidden="true" />
          </Button>
        )}
      </div>

      <ToggleGroup.Root
        type="single"
        value={mode}
        onValueChange={onModeChange}
        aria-label="Answer using"
        className="inline-flex w-fit items-center gap-1 self-start rounded-md bg-fill-tertiary p-1"
      >
        {MODE_OPTIONS.map(({ value, label, Icon }) => (
          <ToggleGroup.Item
            key={value}
            value={value}
            disabled={streaming}
            className={[
              "hit-target inline-flex cursor-pointer items-center gap-1.5 rounded-md px-2.5",
              "text-footnote text-label-secondary transition-colors duration-150 ease-standard",
              "hover:bg-fill-secondary hover:text-label",
              "data-[state=on]:bg-bg data-[state=on]:text-label data-[state=on]:shadow-sm",
              "disabled:pointer-events-none disabled:opacity-40",
            ].join(" ")}
          >
            <Icon className="size-4" strokeWidth={1.5} aria-hidden="true" />
            {label}
          </ToggleGroup.Item>
        ))}
      </ToggleGroup.Root>
    </div>
  );
}

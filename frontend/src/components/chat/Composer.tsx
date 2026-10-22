"use client";

import { useEffect, useRef, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";

export type ComposerProps = {
  onSend: (content: string) => void;
  onStop: () => void;
  streaming: boolean;
};

/** The composer's textarea id, so a keyboard shortcut can focus it from anywhere. */
export const COMPOSER_INPUT_ID = "composer-input";

/**
 * Where a question is written: a sheet of paper at the foot of the
 * conversation, not a pill with a round arrow.
 *
 * The textarea grows with its content up to a cap, so the composer does not
 * jump while somebody is mid-sentence. Enter sends; Shift+Enter is a new line,
 * and the sheet says so. It also says what happens next — Mnemos chooses
 * whether to read documents, query data, call a tool or just answer — because
 * there is deliberately no mode to pick (A4): one surface, and the route is
 * shown beside the answer.
 *
 * While an answer streams the textarea is disabled and Stop takes Send's
 * place, so stopping is always one press away (TRACKER §5 deliverable 5).
 */
export function Composer({ onSend, onStop, streaming }: ComposerProps) {
  const ref = useRef<HTMLTextAreaElement>(null);

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
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="composer shrink-0 bg-bg px-3 pt-2 sm:px-6">
      <div
        className={[
          "flex flex-col rounded-md border border-separator bg-bg-tertiary shadow-sm",
          "transition-[border-color,box-shadow] duration-150 ease-standard",
          "focus-within:border-accent focus-within:shadow-md",
        ].join(" ")}
      >
        <textarea
          ref={ref}
          id={COMPOSER_INPUT_ID}
          rows={1}
          placeholder={streaming ? "Mnemos is answering…" : "Ask about your documents or your data"}
          aria-label="Message"
          aria-describedby="composer-hint"
          disabled={streaming}
          onKeyDown={onKeyDown}
          className={[
            "min-h-12 w-full resize-none bg-transparent px-4 pb-1 pt-3",
            "text-body leading-normal text-label placeholder:text-label-tertiary",
            "focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-60",
          ].join(" ")}
        />
        <div className="flex items-center gap-3 pb-1 pl-4 pr-1">
          <p id="composer-hint" className="min-w-0 flex-1 truncate text-caption text-label-secondary">
            <span className="hidden [@media(hover:hover)_and_(pointer:fine)]:inline">
              <kbd className="font-mono">Enter</kbd> to send · <kbd className="font-mono">Shift Enter</kbd> for a new line ·{" "}
            </span>
            Mnemos picks documents, data or a tool
          </p>
          {streaming ? (
            <Button rank="tinted" aria-label="Stop generating" onClick={onStop} className="shrink-0">
              Stop
            </Button>
          ) : (
            <Button rank="filled" aria-label="Send message" onClick={submit} className="shrink-0">
              Send
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

"use client";

import { Square } from "lucide-react";
import { useEffect, useRef, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/Button";

export type ComposerProps = {
  onSend: (content: string) => void;
  onStop: () => void;
  streaming: boolean;
};

/**
 * A textarea that grows with its content, up to a cap — DesignSystem §4's
 * loading rule extends naturally here: the composer should not itself jump
 * around while somebody is mid-sentence.
 *
 * Enter sends; Shift+Enter inserts a newline. Disabled while a response
 * streams, with a visible stop control in its place (TRACKER §5 deliverable 5).
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
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <div className="flex items-end gap-2 border-t border-separator bg-bg px-4 py-3">
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
        <Button rank="tinted" aria-label="Stop generating" onClick={onStop}>
          <Square className="size-4" strokeWidth={1.5} aria-hidden="true" />
          Stop
        </Button>
      ) : (
        <Button rank="filled" aria-label="Send message" onClick={submit}>
          Send
        </Button>
      )}
    </div>
  );
}

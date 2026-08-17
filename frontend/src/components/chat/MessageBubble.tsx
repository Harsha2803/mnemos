import type { Nl2SqlResult } from "@/lib/chat/stream";
import type { Citation } from "@/lib/knowledge/api";

import { SqlPanel } from "./SqlPanel";

export type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** True for the one assistant bubble currently filling with tokens. */
  streaming?: boolean;
  /**
   * True for the one turn the composer just sent, false/absent for anything
   * loaded from history — the signal `MessageBubble` uses to animate a bubble
   * in only when it genuinely just appeared, not on every conversation open.
   */
  justSent?: boolean;
  /** Present on a RAG answer; the markers in `content` index into these. */
  citations?: Citation[];
  /**
   * Present on an NL2SQL answer received live in this browser session. Not
   * reconstructed from `GET /v1/chat/sessions/{id}` after a reload — the SQL,
   * verdict and rows exist only in the live `done` frame, by design (TRACKER
   * §5 deliverable 5) — so a reloaded historical `nl2sql` message renders as
   * a plain assistant bubble with no panel.
   */
  nl2sql?: Nl2SqlResult;
};

export type MessageBubbleProps = {
  message: DisplayMessage;
  onCitationClick?: (citation: Citation) => void;
};

const MARKER = /(\[\d+\])/g;

/**
 * User and assistant turns are distinguished by side, background *and* an
 * accessible-name label — never colour alone (DesignSystem §3). The streaming
 * bubble carries `aria-live="polite"` so a screen-reader user learns the
 * answer arrived without it being announced token by token.
 *
 * Citation markers become real buttons rather than styled spans: a control
 * that opens a panel is a button, and a `<span onClick>` is invisible to a
 * screen reader and unreachable by keyboard (DesignSystem §3, semantics).
 */
export function MessageBubble({ message, onCitationClick }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={[
        "flex flex-col gap-1",
        isUser ? "items-end" : "items-start",
        // Only the user's own turn animates in: its id never changes after
        // creation. The assistant bubble mounts once (empty, `streaming`)
        // and its `id` is swapped for the server's once the reply finishes
        // (`page.tsx`'s `onDone`) — animating that bubble too would replay
        // the entrance a second time right as the swap remounts it.
        message.justSent === true && isUser ? "animate-fade-in-up" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="px-1 text-footnote text-label-secondary">
        {isUser ? "You" : "Mnemos"}
      </span>
      <div
        aria-live={message.streaming === true ? "polite" : undefined}
        className={[
          "measure whitespace-pre-wrap rounded-lg px-4 py-3 text-body leading-relaxed",
          isUser ? "bg-accent-tint text-label" : "bg-bg-secondary text-label",
        ].join(" ")}
      >
        {message.content.length > 0 ? (
          renderWithCitations(message, onCitationClick)
        ) : (
          <span className="text-label-tertiary">Thinking…</span>
        )}
      </div>
      {/* Outside the `measure`-clamped bubble above, deliberately: tabular
          data wants the full content column, not the 46rem prose measure
          (DesignSystem, TRACKER §5 deliverable 5). Visible inline in the
          conversation, not only behind an inspector click. */}
      {message.nl2sql !== undefined && <SqlPanel result={message.nl2sql} />}
    </div>
  );
}

function renderWithCitations(
  message: DisplayMessage,
  onCitationClick?: (citation: Citation) => void,
) {
  const citations = message.citations ?? [];
  if (citations.length === 0 || onCitationClick === undefined) return message.content;

  return message.content.split(MARKER).map((part, index) => {
    const match = /^\[(\d+)\]$/.exec(part);
    if (match === null) return <span key={index}>{part}</span>;

    const marker = Number(match[1]);
    const citation = citations.find((c) => c.marker === marker);
    if (citation === undefined) return <span key={index}>{part}</span>;

    return (
      <button
        key={index}
        type="button"
        aria-label={`Show source ${marker}`}
        onClick={() => onCitationClick(citation)}
        className="mx-0.5 cursor-pointer rounded-sm bg-accent-tint px-1 align-baseline text-footnote font-semibold text-accent transition-colors duration-150 ease-standard hover:bg-accent-tint-hover"
      >
        {part}
      </button>
    );
  });
}

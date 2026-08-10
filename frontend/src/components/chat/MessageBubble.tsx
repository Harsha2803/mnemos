import type { Citation } from "@/lib/knowledge/api";

export type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** True for the one assistant bubble currently filling with tokens. */
  streaming?: boolean;
  /** Present on a RAG answer; the markers in `content` index into these. */
  citations?: Citation[];
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
    <div className={`flex flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
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
        className="mx-0.5 cursor-pointer rounded-sm bg-accent-tint px-1 align-baseline text-footnote font-semibold text-accent hover:bg-accent-tint-hover"
      >
        {part}
      </button>
    );
  });
}

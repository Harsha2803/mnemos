export type DisplayMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** True for the one assistant bubble currently filling with tokens. */
  streaming?: boolean;
};

/**
 * User and assistant turns are distinguished by side, background *and* an
 * accessible-name label — never colour alone (DesignSystem §3). The streaming
 * bubble carries `aria-live="polite"` so a screen-reader user learns the
 * answer arrived without it being announced token by token (DesignSystem §3,
 * live regions).
 */
export function MessageBubble({ message }: { message: DisplayMessage }) {
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
          message.content
        ) : (
          <span className="text-label-tertiary">Thinking…</span>
        )}
      </div>
    </div>
  );
}

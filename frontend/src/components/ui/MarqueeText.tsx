"use client";

import { useLayoutEffect, useRef, useState } from "react";

export type MarqueeTextProps = {
  text: string;
  className?: string;
};

/** Constant scroll speed rather than a fixed duration, so a long title is not
 * rushed and a short overflow does not crawl. */
const PIXELS_PER_SECOND = 45;

/**
 * A single-line label that scrolls left on hover to reveal whatever its own
 * width was clipping, instead of staying cut off forever. The sidebar's
 * conversation rows (`ChatSessionList.tsx`) are the first use.
 *
 * Only engages when the text actually overflows its box — measured against
 * the rendered width, not guessed from character count, so it stays correct
 * across fonts and zoom levels. A title that already fits never moves.
 */
export function MarqueeText({ text, className }: MarqueeTextProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLSpanElement>(null);
  const [distance, setDistance] = useState(0);
  const [hovering, setHovering] = useState(false);

  useLayoutEffect(() => {
    const container = containerRef.current;
    const textEl = textRef.current;
    if (!container || !textEl) return;

    function measure(): void {
      setDistance(Math.max(0, (textEl?.scrollWidth ?? 0) - (container?.clientWidth ?? 0)));
    }

    measure();
    // Not available in the jsdom test environment; the initial measure above
    // (always 0 there, since jsdom does no real layout) is enough for tests.
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(container);
    return () => observer.disconnect();
  }, [text]);

  const overflowing = distance > 0;

  return (
    <div
      ref={containerRef}
      className={`overflow-hidden ${className ?? ""}`}
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
    >
      <span
        ref={textRef}
        className="inline-block whitespace-nowrap"
        style={
          overflowing
            ? {
                transform: hovering ? `translateX(-${distance}px)` : "translateX(0)",
                transition: `transform ${distance / PIXELS_PER_SECOND}s linear`,
              }
            : undefined
        }
      >
        {text}
      </span>
    </div>
  );
}

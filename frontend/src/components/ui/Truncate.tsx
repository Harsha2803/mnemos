"use client";

import { useLayoutEffect, useRef, useState } from "react";

export type TruncateProps = {
  text: string;
  className?: string;
};

/**
 * One line, ellipsised — and the whole value on hover *and* keyboard focus.
 *
 * Long titles, paths and IDs are the norm here, and an ellipsis with no way to
 * read the rest is a dead end. The full text is laid over the clipped line
 * (wrapping within the same width, on the raised surface) when the nearest
 * `group/truncate` ancestor is hovered or contains focus. That ancestor is the
 * row or link, so the reveal follows whatever the person is pointing at or
 * tabbing through. The overlay stays inside the row's own width, so a
 * scrolling sidebar never clips it sideways.
 *
 * It appears only when the text genuinely overflows — measured, not guessed —
 * and it is generated content, so assistive technology hears the text once
 * (the element's own text already carries all of it). `title` covers the
 * pointer case in contexts without the group.
 */
export function Truncate({ text, className = "" }: TruncateProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const [overflowing, setOverflowing] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (element === null) return;
    const measure = () => setOverflowing(element.scrollWidth > element.clientWidth + 1);
    measure();
    // jsdom has no ResizeObserver and no layout; the first measure (always
    // "fits" there) is all a unit test can observe anyway.
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text]);

  return (
    // Two spans: the inner one clips, so the reveal hangs off the outer one —
    // a pseudo-element on the clipping span would be clipped with it.
    <span
      data-full={overflowing ? text : undefined}
      className={[
        "relative block min-w-0",
        // The reveal is a pseudo-element reading `data-full`, not a second
        // copy of the text in the DOM, so a text query still finds one match.
        overflowing
          ? [
              "after:pointer-events-none after:absolute after:-inset-x-2 after:-top-1 after:z-20",
              "after:hidden after:whitespace-normal after:break-words after:rounded-sm after:px-2 after:py-1",
              "after:bg-bg-tertiary after:text-label after:shadow-md after:content-[attr(data-full)]",
              "group-hover/truncate:after:block group-focus-within/truncate:after:block",
            ].join(" ")
          : "",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span ref={ref} className="block truncate" title={overflowing ? text : undefined}>
        {text}
      </span>
    </span>
  );
}

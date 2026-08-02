"use client";

import { Skeleton } from "@/components/ui/Skeleton";

import { useReadiness } from "./useReadiness";

type Presentation = {
  label: string;
  /** A token class, never a raw colour. */
  dot: string;
  text: string;
};

/**
 * Colour is never the only signal (DesignSystem §3): every state carries a word
 * as well as a dot. Around 8% of men have a colour-vision deficiency, and a
 * green dot and an amber one are the pair they are most likely to confuse.
 */
function present(status: "ready" | "degraded" | "unreachable"): Presentation {
  switch (status) {
    case "ready":
      return { label: "API ready", dot: "bg-success", text: "text-label-secondary" };
    case "degraded":
      return { label: "API degraded", dot: "bg-warning", text: "text-warning" };
    case "unreachable":
      return { label: "API unreachable", dot: "bg-danger", text: "text-danger" };
  }
}

export function HealthIndicator() {
  const { data, isPending, isError } = useReadiness();

  if (isPending) {
    return (
      <div className="flex items-center gap-2 px-2 py-1">
        <Skeleton label="Checking API readiness" className="h-2.5 w-2.5 rounded-full" />
        <Skeleton className="h-3 w-24" />
      </div>
    );
  }

  const status = isError ? "unreachable" : data.ready ? "ready" : "degraded";
  const { label, dot, text } = present(status);

  return (
    // `aria-live` so a screen-reader user learns the API went away, rather than
    // only seeing it if they happen to be reading the sidebar at the time.
    <p
      aria-live="polite"
      className={`flex items-center gap-2 px-2 py-1 text-footnote ${text}`}
    >
      <span aria-hidden="true" className={`size-2.5 shrink-0 rounded-full ${dot}`} />
      {label}
    </p>
  );
}

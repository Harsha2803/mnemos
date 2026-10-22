"use client";

import { Button } from "./Button";

export type LoadErrorProps = {
  /** What failed to load, as the reader would name it: "Your documents". */
  what: string;
  error: Error | null;
  /** Try the request again. Omitted only where a retry cannot help. */
  onRetry?: () => void;
};

/**
 * A list that failed to load says so — never an empty state.
 *
 * "No documents yet" over a failed request tells the reader something false:
 * that the library is empty. So a failure gets its own shape: a carmine rule,
 * what could not be loaded, the reason in the API's words, and a way to try
 * again where the page cannot otherwise recover (DesignSystem §4).
 */
export function LoadError({ what, error, onRetry }: LoadErrorProps) {
  return (
    <div role="alert" className="flex flex-col items-start gap-2 border-l-2 border-danger py-1 pl-3">
      <p className="text-callout text-label">
        {what} could not be loaded
        {error !== null && error.message !== "" && <span className="text-label-secondary"> ({error.message})</span>}.
      </p>
      {onRetry !== undefined && (
        <Button rank="plain" className="!px-0 text-footnote" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

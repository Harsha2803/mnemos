import { absoluteTime, relativeLong, relativeShort } from "@/lib/time";

export type RelativeTimeProps = {
  /** ISO 8601 timestamp from the API. */
  value: string;
  /** `short` ("2h") for dense rows, `long` ("2 hours ago") for prose. */
  form?: "short" | "long";
  className?: string;
  /**
   * Id for the spoken exact time, so a control containing this element can
   * point `aria-describedby` at it and keep the time out of its *name*.
   */
  id?: string;
};

/**
 * A `<time>` that reads relative and knows the exact moment.
 *
 * The absolute time is the hover tooltip (`title`) *and* part of the accessible
 * name, so a screen-reader or keyboard user gets the precise moment without
 * having to hover — a relative "2h" on its own is a figure that goes stale the
 * minute it is read.
 */
export function RelativeTime({ value, form = "short", className = "", id }: RelativeTimeProps) {
  const exact = absoluteTime(value);
  const relative = form === "short" ? relativeShort(value) : relativeLong(value);
  return (
    <time dateTime={value} title={exact} className={className}>
      <span aria-hidden="true">{relative}</span>
      <span id={id} className="sr-only">
        {exact}
      </span>
    </time>
  );
}

/**
 * Time, as the interface shows it: relative where recency is the question
 * ("2h ago"), absolute where the exact moment is ("22 Oct 2026, 08:00"), and
 * always both available — the relative form on the page, the absolute form on
 * hover and focus (`RelativeTime`).
 *
 * One module, so "how long ago" has one wording across the sidebar, the
 * overview ledger and ingestion activity rather than three that drift.
 */

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "now", "4m", "2h", "3d", then a short date. Compact, for dense rows. */
export function relativeShort(iso: string, now: number = Date.now()): string {
  const elapsed = Math.max(0, now - Date.parse(iso));
  if (elapsed < MINUTE) return "now";
  if (elapsed < HOUR) return `${Math.floor(elapsed / MINUTE)}m`;
  if (elapsed < DAY) return `${Math.floor(elapsed / HOUR)}h`;
  if (elapsed < 7 * DAY) return `${Math.floor(elapsed / DAY)}d`;
  return new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" }).format(new Date(iso));
}

/** "just now", "4 minutes ago", "yesterday", "3 days ago", then a date. For prose. */
export function relativeLong(iso: string, now: number = Date.now()): string {
  const elapsed = Math.max(0, now - Date.parse(iso));
  if (elapsed < MINUTE) return "just now";
  if (elapsed < HOUR) return plural(Math.floor(elapsed / MINUTE), "minute");
  if (elapsed < DAY) return plural(Math.floor(elapsed / HOUR), "hour");
  if (elapsed < 2 * DAY) return "yesterday";
  if (elapsed < 7 * DAY) return plural(Math.floor(elapsed / DAY), "day");
  return `on ${new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(iso))}`;
}

/** The exact moment, in the reader's locale and timezone. */
export function absoluteTime(iso: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

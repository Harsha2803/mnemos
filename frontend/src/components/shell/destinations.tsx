export type Destination = {
  href: string;
  label: string;
  /**
   * Which of the three kinds of work the destination belongs to: reading and
   * asking, the library Mnemos answers from, and operating it. The sidebar
   * leaves a little space between groups instead of drawing an icon per row.
   */
  group: "read" | "library" | "operate";
};

/**
 * Only destinations that exist.
 *
 * The sidebar grows a row per milestone — sources at B1 — and a row that
 * leads nowhere is worse than a short list, because the user cannot tell
 * "not built yet" from "broken".
 *
 * The sidebar and the toolbar title both read this list, so the label in the
 * bar is the label in the nav by construction rather than by coincidence.
 */
export const DESTINATIONS: readonly Destination[] = [
  { href: "/", label: "Overview", group: "read" },
  { href: "/chat", label: "Chat", group: "read" },
  { href: "/bookmarks", label: "Bookmarks", group: "read" },
  { href: "/knowledge", label: "Knowledge", group: "library" },
  { href: "/memory", label: "Memory", group: "library" },
  { href: "/sources", label: "Sources", group: "library" },
  { href: "/tools", label: "Tools", group: "operate" },
  { href: "/audit", label: "Audit log", group: "operate" },
];

/**
 * `/chat/[sessionId]` should still read as the Chat destination in the
 * toolbar title, so every destination but the root matches by prefix; the
 * root is matched exactly or it would swallow every other route.
 */
export function destinationFor(pathname: string | null): Destination | undefined {
  if (pathname === null) return undefined;
  return DESTINATIONS.find((destination) =>
    destination.href === "/" ? pathname === "/" : pathname.startsWith(destination.href),
  );
}

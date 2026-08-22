import { Bookmark, Brain, FileText, LayoutGrid, MessageCircle, Plug, Wrench, type LucideIcon } from "lucide-react";

export type Destination = {
  href: string;
  label: string;
  Icon: LucideIcon;
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
  { href: "/", label: "Overview", Icon: LayoutGrid },
  { href: "/chat", label: "Chat", Icon: MessageCircle },
  { href: "/bookmarks", label: "Bookmarks", Icon: Bookmark },
  { href: "/knowledge", label: "Knowledge", Icon: FileText },
  { href: "/memory", label: "Memory", Icon: Brain },
  { href: "/sources", label: "Sources", Icon: Plug },
  { href: "/tools", label: "Tools", Icon: Wrench },
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

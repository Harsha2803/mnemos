import { LayoutGrid, type LucideIcon } from "lucide-react";

export type Destination = {
  href: string;
  label: string;
  Icon: LucideIcon;
};

/**
 * Only destinations that exist.
 *
 * The sidebar grows a row per milestone — sources at M5, knowledge at M6, chat
 * at M8 — and a row that leads nowhere is worse than a short list, because the
 * user cannot tell "not built yet" from "broken".
 *
 * The sidebar and the toolbar title both read this list, so the label in the
 * bar is the label in the nav by construction rather than by coincidence.
 */
export const DESTINATIONS: readonly Destination[] = [
  { href: "/", label: "Overview", Icon: LayoutGrid },
];

export function destinationFor(pathname: string | null): Destination | undefined {
  return DESTINATIONS.find((destination) => destination.href === pathname);
}

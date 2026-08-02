"use client";

import { LayoutGrid } from "lucide-react";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { List, ListItem } from "@/components/ui/List";

import { HealthIndicator } from "./HealthIndicator";

type Destination = {
  href: string;
  label: string;
  icon: ReactNode;
};

/**
 * Only destinations that exist. The sidebar grows a row per milestone — chat at
 * M8, knowledge at M6, sources at M5 — and a row that leads nowhere is worse
 * than a short list, because the user cannot tell "not built" from "broken".
 */
const DESTINATIONS: readonly Destination[] = [
  {
    href: "/",
    label: "Overview",
    icon: <LayoutGrid className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />,
  },
];

export function SidebarContent() {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="px-2 pt-1">
        <p className="text-title-3 font-semibold tracking-title text-label">Mnemos</p>
        <p className="text-footnote text-label-secondary">Workspace</p>
      </div>

      <List label="Sections">
        {DESTINATIONS.map(({ href, label, icon }) => (
          <ListItem key={href} href={href} current={pathname === href} leading={icon}>
            {label}
          </ListItem>
        ))}
      </List>

      {/* The footer is where the signed-in user lands at M3.4. Until then it
          carries the one fact the shell can already state truthfully: whether
          the API behind it is answering. */}
      <div className="mt-auto border-t border-separator pt-2">
        <HealthIndicator />
      </div>
    </div>
  );
}

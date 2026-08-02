"use client";

import { usePathname } from "next/navigation";

import { List, ListItem } from "@/components/ui/List";

import { DESTINATIONS } from "./destinations";
import { HealthIndicator } from "./HealthIndicator";

export function SidebarContent() {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="px-2 pt-1">
        <p className="text-title-3 font-semibold tracking-title text-label">Mnemos</p>
        <p className="text-footnote text-label-secondary">Workspace</p>
      </div>

      <List label="Sections">
        {DESTINATIONS.map(({ href, label, Icon }) => (
          <ListItem
            key={href}
            href={href}
            current={pathname === href}
            leading={<Icon className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />}
          >
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

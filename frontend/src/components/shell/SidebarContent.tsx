"use client";

import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { usePathname } from "next/navigation";

import { ChatSessionList } from "@/components/chat/ChatSessionList";
import { List, ListItem } from "@/components/ui/List";

import { AccountFooter } from "./AccountFooter";
import { DESTINATIONS } from "./destinations";
import { HealthIndicator } from "./HealthIndicator";

export function SidebarContent({
  headerAction,
  mobile = false,
}: { headerAction?: ReactNode; mobile?: boolean } = {}) {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <div className="flex shrink-0 items-start justify-between gap-2 px-2 pt-1">
        <div>
          <p className="text-title-3 font-semibold tracking-title text-label">Mnemos</p>
          <p className="text-footnote text-label-secondary">Workspace</p>
        </div>
        {headerAction}
      </div>

      {/* `shrink-0` on the destinations, and the scroll on the conversations
          rather than on the pair. A flex child shrinks below its content by
          default, so with enough conversations the destinations were being
          squeezed until the "Conversations" header overlapped them and
          swallowed clicks meant for the nav — found by running the Playwright
          specs in sequence against a stack that had accumulated sessions,
          which is exactly the failure a fresh single-spec run cannot see. */}
      <List label="Sections" className="shrink-0">
        {DESTINATIONS.map(({ href, label, Icon }) => (
          <ListItem
            key={href}
            href={href}
            current={href === "/" ? pathname === "/" : pathname?.startsWith(href) === true}
            leading={<Icon className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />}
          >
            {label}
          </ListItem>
        ))}
      </List>

      <div className={mobile ? "flex-1" : "min-h-0 flex-1 overflow-y-auto"}>
        <ChatSessionList />
      </div>

      {/* The footer the shell reserved at F0, now carrying a real identity
          rather than a placeholder: who is signed in, which tenant, and the way
          out. The readiness line stays underneath it — "the API is unreachable"
          and "you are signed out" send whoever reads them to different places,
          and collapsing the two would cost real debugging time. */}
      <div className="mt-auto flex flex-col gap-1 border-t border-separator pt-2">
        {mobile && <div className="flex flex-wrap items-center justify-between gap-2 pb-2"><span className="text-footnote text-label-secondary">Appearance</span><ThemeToggle /></div>}
        <AccountFooter />
        <HealthIndicator />
      </div>
    </div>
  );
}

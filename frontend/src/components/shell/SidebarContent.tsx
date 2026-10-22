"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment, type ReactNode } from "react";

import { ChatSessionList } from "@/components/chat/ChatSessionList";

import { AccountMenu } from "./AccountMenu";
import { DESTINATIONS } from "./destinations";
import { HealthIndicator } from "./HealthIndicator";

/**
 * The sidebar: wordmark, sections, conversations, account.
 *
 * Typographic rather than a stack of icon rows in a grey card. The current
 * section is marked by weight, ink and a short rubric rule — the same red the
 * rest of the app uses for "this one" — and `aria-current`, never colour alone.
 * Sections fall into three groups separated by space, which carries the
 * structure an icon per row was only decorating.
 */
export function SidebarContent({
  headerAction,
  mobile = false,
}: { headerAction?: ReactNode; mobile?: boolean } = {}) {
  const pathname = usePathname();

  return (
    <div className="flex h-full flex-col gap-5 px-3 pb-3 pt-4">
      <div className="flex shrink-0 items-center justify-between gap-2 pl-3">
        <Link
          href="/"
          className="hit-target -my-2 inline-flex items-center font-serif text-title-2 font-semibold tracking-title text-label"
        >
          Mnemos
        </Link>
        {headerAction}
      </div>

      {/* `shrink-0` on the sections and the scroll on the conversations rather
          than on the pair: a flex child shrinks below its content by default,
          and with enough conversations the sections were once squeezed until
          the "Conversations" header overlapped them and swallowed clicks. */}
      <ul aria-label="Sections" className="flex shrink-0 flex-col">
        {DESTINATIONS.map(({ href, label, group }, index) => {
          const current = href === "/" ? pathname === "/" : pathname?.startsWith(href) === true;
          const startsGroup = index > 0 && DESTINATIONS[index - 1]?.group !== group;
          return (
            <Fragment key={href}>
              {startsGroup && <li aria-hidden="true" className="h-2" />}
              <li>
                <Link
                  href={href}
                  aria-current={current ? "page" : undefined}
                  className={[
                    "hit-target relative flex items-center rounded-sm pl-3 pr-2 text-callout",
                    "text-label-secondary transition-colors duration-150 ease-standard",
                    "hover:bg-fill-tertiary hover:text-label",
                    "aria-[current=page]:font-semibold aria-[current=page]:text-label",
                    "before:absolute before:inset-y-3 before:left-0 before:w-0.5 before:rounded-full",
                    "before:bg-transparent aria-[current=page]:before:bg-rubric",
                  ].join(" ")}
                >
                  {label}
                </Link>
              </li>
            </Fragment>
          );
        })}
      </ul>

      <div className={mobile ? "flex-1" : "-mx-1 min-h-0 flex-1 overflow-y-auto px-1"}>
        <ChatSessionList />
      </div>

      {/* "The API is unreachable" and "you are signed out" send whoever reads
          them to different places, so readiness keeps its own line under the
          account rather than folding into it. */}
      <div className="mt-auto flex flex-col gap-1 border-t border-separator pt-2">
        <AccountMenu />
        <HealthIndicator />
      </div>
    </div>
  );
}

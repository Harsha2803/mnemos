"use client";

import * as Popover from "@radix-ui/react-popover";
import { ChevronsUpDown } from "lucide-react";
import { useState } from "react";

import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/lib/auth/AuthProvider";

/**
 * Who is signed in, to which workspace — and, one click deeper, how the app
 * looks and the way out.
 *
 * The email and org stay on the trigger, always visible: every row in this
 * application is scoped to one org, and somebody with access to two can read
 * the wrong one's numbers for a long time before anything looks wrong. The
 * trigger's accessible name is that visible text, so what a sighted user reads
 * is what a screen reader announces.
 *
 * Appearance lives here rather than in the toolbar. It is set once and rarely
 * revisited, and three theme buttons were spending the most valuable chrome
 * on screen on it. Sign-out lives here too, still named for the workspace it
 * leaves.
 *
 * Both values come from `GET /auth/me`, resolved on the request that asks; the
 * access token carries no email and no org slug, by design.
 */
export function AccountMenu() {
  const { identity, signOut } = useAuth();
  const [signingOut, setSigningOut] = useState(false);

  if (identity === null) {
    return (
      <div className="flex flex-col gap-1 px-3 py-2">
        <Skeleton label="Loading your account" className="h-3.5 w-32" />
        <Skeleton className="h-3 w-20" aria-hidden="true" />
      </div>
    );
  }

  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <button
          type="button"
          className={[
            "hit-target group/account flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left",
            "transition-colors duration-150 ease-standard hover:bg-fill-tertiary",
            "data-[state=open]:bg-fill-secondary",
          ].join(" ")}
        >
          <span className="min-w-0 flex-1">
            <span className="block truncate text-footnote font-medium text-label" title={identity.email}>
              {identity.email}
            </span>
            <span className="block truncate font-mono text-caption text-label-secondary">
              {identity.org_slug}
            </span>
          </span>
          <ChevronsUpDown
            className="size-4 shrink-0 text-label-tertiary transition-colors group-hover/account:text-label-secondary"
            strokeWidth={1.5}
            aria-hidden="true"
          />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={6}
          collisionPadding={12}
          aria-label="Account"
          className={[
            "popover-content z-50 flex w-[min(18rem,calc(100vw-1.5rem))] flex-col gap-4",
            "rounded-lg border border-separator bg-bg-tertiary p-4 text-label shadow-md",
          ].join(" ")}
        >
          <div className="min-w-0">
            {identity.display_name !== null && identity.display_name !== "" && (
              <p className="truncate text-callout font-semibold">{identity.display_name}</p>
            )}
            <p className="break-all text-footnote text-label-secondary">{identity.email}</p>
            <p className="mt-2 font-mono text-caption uppercase tracking-caps text-label-secondary">
              Workspace · {identity.org_slug}
            </p>
          </div>

          <div className="flex flex-col gap-2 border-t border-separator pt-3">
            <span className="font-mono text-caption uppercase tracking-caps text-label-secondary">
              Appearance
            </span>
            <ThemeToggle />
          </div>

          <div className="flex flex-col border-t border-separator pt-3">
            <Popover.Close asChild>
              <Button
                rank="plain"
                className="w-full !justify-between !px-2 !font-medium !text-label"
                onClick={() => window.dispatchEvent(new Event("mnemos:shortcuts"))}
              >
                Keyboard shortcuts
                <kbd className="rounded-sm border border-separator px-1.5 font-mono text-caption text-label-secondary">?</kbd>
              </Button>
            </Popover.Close>
            <Button
              rank="plain"
              className="w-full !justify-start !px-2"
              disabled={signingOut}
              onClick={() => {
                // Latched rather than reset in a `finally`: `signOut` navigates
                // away, and re-enabling the control on an unmounting component
                // is a second chance to fire a second revoke.
                setSigningOut(true);
                void signOut();
              }}
            >
              {/* The visible words are the accessible name, and they name the
                  workspace being left. */}
              {signingOut ? "Signing out…" : `Sign out of ${identity.org_slug}`}
            </Button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

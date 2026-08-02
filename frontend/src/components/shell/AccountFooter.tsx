"use client";

import { LogOut } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/lib/auth/AuthProvider";

/**
 * Who is signed in, and which tenant they are signed in to.
 *
 * The org is shown next to the email and not only implied by the data on
 * screen. Every row in this application is scoped to one org, and somebody with
 * access to two of them can otherwise spend a long time reading the wrong one's
 * numbers before anything looks wrong.
 *
 * Both values come from `GET /auth/me`, which resolves them from the database on
 * the request that asks — the access token carries no email and no org slug, by
 * design. The shell had a placeholder here until now; this is where it becomes
 * real.
 */
export function AccountFooter() {
  const { identity, signOut } = useAuth();
  const [signingOut, setSigningOut] = useState(false);

  if (identity === null) {
    return (
      <div className="flex flex-col gap-1 px-2 py-1">
        <Skeleton label="Loading your account" className="h-3.5 w-32" />
        <Skeleton className="h-3 w-20" aria-hidden="true" />
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 px-2 py-1">
      <div className="min-w-0 flex-1">
        {/* `truncate` with a `title`, because an email is exactly the kind of
            value that is both too long for 260px and useless when abbreviated. */}
        <p className="truncate text-footnote font-semibold text-label" title={identity.email}>
          {identity.email}
        </p>
        <p className="truncate text-caption text-label-secondary">{identity.org_slug}</p>
      </div>
      <Button
        aria-label={`Sign out of ${identity.org_slug}`}
        disabled={signingOut}
        onClick={() => {
          // Latched rather than reset in a `finally`: `signOut` navigates away,
          // and re-enabling the control on an unmounting component is both
          // pointless and a second chance to fire a second revoke.
          setSigningOut(true);
          void signOut();
        }}
      >
        <LogOut className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />
      </Button>
    </div>
  );
}

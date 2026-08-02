"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/lib/auth/AuthProvider";
import { signInHrefFor } from "@/lib/auth/destination";

/**
 * Nothing inside renders until the API has said who the caller is.
 *
 * **The redirect preserves the intended destination.** Somebody who followed a
 * link to a specific screen, signed in, and landed on the home page has been
 * made to navigate twice for no reason — and by the second time they often
 * cannot remember what the link was. `signInHrefFor` carries the path through as
 * `?next=`, and `destination.ts` validates it on the way back out so it cannot
 * be turned into an off-origin redirect.
 *
 * **This is a courtesy, never the control.** The API authenticates every route
 * by default and hydrates authority from the database on every request; a user
 * who defeats this component by editing their own JavaScript reaches a shell
 * whose every call answers 401. Client-side route protection that is *believed*
 * to be a security boundary is how an unauthenticated API endpoint survives
 * review.
 */
export function AuthBoundary({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") router.replace(signInHrefFor(pathname));
  }, [status, router, pathname]);

  if (status === "authenticated") return <>{children}</>;

  // A skeleton in the shape of the thing that is coming, never a spinner over a
  // blank region (DesignSystem §4): a spinner discards the layout information
  // the user is about to need. One label for the region, not one per shape —
  // six live regions all announcing "loading" is worse than none.
  return (
    <div
      role="status"
      aria-label={status === "unknown" ? "Checking your session" : "Returning to sign in"}
      className="flex h-dvh flex-col gap-6 bg-bg p-8"
    >
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-4 w-full max-w-[var(--measure)]" aria-hidden="true" />
      <Skeleton className="h-4 w-3/4 max-w-[var(--measure)]" aria-hidden="true" />
      <Skeleton className="h-40 w-full max-w-[var(--measure)]" aria-hidden="true" />
    </div>
  );
}

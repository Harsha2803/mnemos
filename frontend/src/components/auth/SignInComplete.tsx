"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/lib/auth/AuthProvider";
import { SIGN_IN_PATH, takeDestination } from "@/lib/auth/destination";

/**
 * Where Keycloak's callback puts the browser down.
 *
 * By the time this renders, the API has set the refresh cookie and sent us back
 * here **carrying no token in the URL**. `AuthProvider` is already exchanging
 * that cookie for an access token — the same exchange a reload performs — so
 * this component does nothing but wait for the answer and then leave.
 *
 * The waiting state is a skeleton and not a spinner, and it is announced once
 * (DesignSystem §4). Nobody should be here for more than a round trip, but a
 * blank white page during that round trip is indistinguishable from a broken
 * login, which is the impression to avoid on the screen immediately after a
 * password was typed.
 */
export function SignInComplete() {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace(takeDestination());
    // A cookie that did not work, or a callback somebody navigated to by hand.
    else if (status === "anonymous") router.replace(SIGN_IN_PATH);
  }, [status, router]);

  return (
    <main className="flex min-h-dvh items-center justify-center bg-bg-grouped px-6">
      <div className="flex w-full max-w-md flex-col gap-4">
        <Skeleton label="Finishing sign in" className="h-8 w-48" />
        <Skeleton className="h-4 w-full" aria-hidden="true" />
        <Skeleton className="h-4 w-2/3" aria-hidden="true" />
      </div>
    </main>
  );
}

"use client";

import { useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { fetchIdentity } from "@/lib/auth/identity";
import { refreshAccessToken, signOut as revokeSession } from "@/lib/auth/refresh";
import {
  clearSession,
  getServerSessionSnapshot,
  getSessionSnapshot,
  setIdentity,
  subscribeToSession,
  type AuthStatus,
  type Identity,
} from "@/lib/auth/session";
import { SIGN_IN_PATH } from "@/lib/auth/destination";

export type AuthContextValue = {
  status: AuthStatus;
  identity: Identity | null;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Bootstraps the session on mount and exposes it to the tree.
 *
 * **The cold-load path is the refresh path.** A reload loses the in-memory
 * access token, so the first thing the app does is exchange the `httpOnly`
 * refresh cookie for a new one — which is exactly what a 401 does later. One
 * code path for "stay signed in across a reload" and "recover from an expired
 * token" means the two cannot drift into disagreeing about what a failure looks
 * like.
 *
 * The store is read through `useSyncExternalStore` because it is also written
 * from the fetch layer, outside any component, when a refresh lands mid-request.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const snapshot = useSyncExternalStore(
    subscribeToSession,
    getSessionSnapshot,
    getServerSessionSnapshot,
  );
  const router = useRouter();
  const bootstrapped = useRef(false);

  useEffect(() => {
    // React 18+ mounts effects twice in development StrictMode. Two bootstraps
    // are two refreshes, and two refreshes of one cookie is precisely the
    // concurrent use the backend treats as theft — so this guard is not a
    // micro-optimisation, it is the difference between a dev server that works
    // and one that signs you out on every hot reload.
    if (bootstrapped.current) return;
    bootstrapped.current = true;

    let cancelled = false;
    void (async () => {
      try {
        const token = await refreshAccessToken();
        if (cancelled) return;
        if (token === null) {
          clearSession();
          return;
        }
        const identity = await fetchIdentity();
        if (cancelled) return;
        if (identity === null) clearSession();
        else setIdentity(identity);
      } catch {
        // `fetchIdentity` throws on a 5xx — an API that answered but could not
        // say who this is. Anonymous is the honest reading and the recoverable
        // one: the sign-in screen is reachable and a retry costs a click.
        // Without the catch this is an unhandled rejection in a chain nobody is
        // awaiting, which is a browser console error and, in the test runner, a
        // failed run after every test has passed.
        if (!cancelled) clearSession();
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const signOut = useCallback(async () => {
    try {
      await revokeSession();
    } catch {
      // `revokeSession` clears local state in a `finally` and then rethrows, so
      // a transport failure has already signed the user out of *this* browser.
      // Refusing to navigate on top of that would leave them looking at a shell
      // whose every request now 401s, which is the worst of both answers.
    }
    router.replace(SIGN_IN_PATH);
  }, [router]);

  return (
    <AuthContext.Provider
      value={{ status: snapshot.status, identity: snapshot.identity, signOut }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (value === null) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return value;
}

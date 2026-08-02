/**
 * The access token, and nothing else, held in a module variable.
 *
 * **In memory only.** Not `localStorage`, not `sessionStorage`, not a
 * non-`httpOnly` cookie — every one of those is readable by any script the page
 * ends up running, which is the whole of what a cross-site scripting bug buys an
 * attacker. The long-lived half of the credential never reaches JavaScript at
 * all: the API sets it as an `httpOnly` cookie, so the worst an injected script
 * can do is *use* the session in the page it already controls, rather than walk
 * away with fourteen days of it.
 *
 * The cost is that a reload loses the token, which is why `bootstrapSession`
 * exists: on a cold load the app exchanges the cookie for a fresh access token
 * over `POST /auth/token`. That is the same call a 401 triggers, so "stay signed
 * in across a reload" and "recover from an expired token" are one code path
 * rather than two that can disagree.
 *
 * Nothing here imports React. The store is read through `useSyncExternalStore`
 * in `AuthProvider`, because the value is also written from the fetch layer —
 * outside any component — when a refresh lands.
 */

import type { components } from "@/lib/api/schema";

/** Generated from the API's own OpenAPI document; never hand-written. */
export type Identity = components["schemas"]["MeResponse"];

export type AuthStatus =
  /** A cold load that has not yet asked the cookie whether it is anybody. */
  | "unknown"
  /** Asked, and the answer was no. */
  | "anonymous"
  /** Holding a live access token. */
  | "authenticated";

export type SessionSnapshot = {
  status: AuthStatus;
  identity: Identity | null;
};

let accessToken: string | null = null;

// A frozen snapshot object, replaced rather than mutated. `useSyncExternalStore`
// compares snapshots by identity and re-renders on every change, so returning a
// freshly-built object on each read would loop forever.
let snapshot: SessionSnapshot = { status: "unknown", identity: null };

const listeners = new Set<() => void>();

function publish(next: SessionSnapshot): void {
  snapshot = next;
  for (const listener of listeners) listener();
}

export function subscribeToSession(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getSessionSnapshot(): SessionSnapshot {
  return snapshot;
}

/**
 * The server-rendered snapshot. Always "unknown": the server has no cookie jar
 * for this user and must not pretend to know. Rendering "anonymous" on the
 * server would flash a sign-in screen at somebody who is signed in.
 */
export function getServerSessionSnapshot(): SessionSnapshot {
  return { status: "unknown", identity: null };
}

/** The token the fetch layer attaches. Deliberately not exported to React. */
export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string): void {
  accessToken = token;
  if (snapshot.status !== "authenticated") {
    publish({ status: "authenticated", identity: snapshot.identity });
  }
}

export function setIdentity(identity: Identity): void {
  publish({ status: "authenticated", identity });
}

/**
 * Forget everything. Called when a refresh fails, when the second 401 arrives,
 * and on sign-out.
 *
 * It does **not** clear the refresh cookie — it cannot, because the cookie is
 * `httpOnly`. Only `POST /auth/token:revoke` can, and that is what `signOut`
 * calls. A client that cleared its own state and left the cookie standing would
 * look signed out and be one page load from signed in again.
 */
export function clearSession(): void {
  accessToken = null;
  publish({ status: "anonymous", identity: null });
}

/** Test seam. Resets the module between cases without exporting the internals. */
export function resetSessionForTests(): void {
  accessToken = null;
  snapshot = { status: "unknown", identity: null };
  listeners.clear();
}

/**
 * Exchanging the refresh cookie for an access token — **exactly once at a time.**
 *
 * This is a correctness requirement and not an optimisation, and the reason is
 * in the backend: every use of a refresh token rotates it, and presenting a
 * token whose row already names a successor is treated as proof of theft, so
 * the entire rotation chain is revoked. Losing the compare-and-set counts as
 * the same evidence. A client that fires five requests, gets five 401s and
 * refreshes five times therefore **signs itself out** — one refresh wins and
 * the other four are indistinguishable from a stolen credential being replayed.
 * TRACKER §4 items 23 and 26 record the decision; this module is where the
 * client keeps its side of the bargain.
 *
 * Two scopes, and they need different mechanisms:
 *
 * *Within a tab*, concurrent callers share one promise. The second caller does
 * not start a second refresh — it awaits the first one's result and uses the
 * token that comes back.
 *
 * *Across tabs*, a shared promise does not exist, so the calls are serialized
 * with the **Web Locks API**. Serializing rather than sharing is deliberate and
 * is what makes it safe: tab B waits, then performs its own refresh against the
 * cookie tab A has already rotated, and both succeed. Sharing the *token*
 * across tabs would mean writing it somewhere both can read, which is the
 * `localStorage` this whole design exists to avoid. Web Locks is absent in
 * jsdom and in older Safari, so the in-tab promise is the fallback and the
 * residue is written down in TRACKER §4.
 */

import { API_BASE_URL } from "@/lib/api/client";
import { clearSession, setAccessToken } from "@/lib/auth/session";

export const TOKEN_PATH = "/api/v1/auth/token";
export const REVOKE_PATH = "/api/v1/auth/token:revoke";
export const ME_PATH = "/api/v1/auth/me";

/** One name, so two tabs of this app contend and two apps do not. */
export const REFRESH_LOCK = "mnemos.auth.refresh";

let inFlight: Promise<string | null> | null = null;

/**
 * A new access token, or `null` if the cookie is gone, expired or revoked.
 *
 * Never rejects on a denial. "You are not signed in" is an answer, and a caller
 * that had to distinguish a rejected promise from a resolved `null` would end
 * up branching on an error message — which the API deliberately makes identical
 * for every cause.
 */
export function refreshAccessToken(): Promise<string | null> {
  if (inFlight !== null) return inFlight;

  inFlight = withRefreshLock(performRefresh).finally(() => {
    inFlight = null;
  });
  return inFlight;
}

async function performRefresh(): Promise<string | null> {
  let response: Response;
  try {
    response = await globalThis.fetch(`${API_BASE_URL}${TOKEN_PATH}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      // The cookie is `httpOnly` and cross-origin, so nothing is sent without
      // this. Its absence is the single most common reason a refresh that looks
      // correct returns 401 forever.
      credentials: "include",
      body: JSON.stringify({ grant_type: "refresh_token" }),
    });
  } catch {
    // The API is unreachable. Not a denial: signing the user out because their
    // laptop slept would be the wrong reading of a network error.
    return null;
  }

  if (!response.ok) {
    clearSession();
    return null;
  }

  const body: unknown = await response.json();
  const token = readAccessToken(body);
  if (token === null) {
    clearSession();
    return null;
  }
  setAccessToken(token);
  return token;
}

/**
 * Serialize across tabs when the browser can, and do not pretend to when it
 * cannot.
 *
 * `navigator.locks` is unavailable in jsdom and in Safari before 15.4. Falling
 * back to running unsynchronised is the honest behaviour: it is exactly what the
 * app did before, and it is bounded by the in-tab promise above.
 */
async function withRefreshLock<T>(work: () => Promise<T>): Promise<T> {
  const locks = globalThis.navigator?.locks;
  if (locks === undefined) return work();
  return locks.request(REFRESH_LOCK, work);
}

function readAccessToken(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const token = (body as Record<string, unknown>)["access_token"];
  return typeof token === "string" && token.length > 0 ? token : null;
}

/**
 * Sign out: revoke the refresh chain server-side, then forget the token here.
 *
 * The order matters. Clearing local state first and then failing to reach the
 * API would leave a live refresh cookie in the browser and a UI insisting the
 * user is signed out — one reload from proving itself wrong. The local clear
 * happens either way, because a user who asked to sign out on a flaky
 * connection should not stay signed in.
 *
 * `token:revoke` always answers 204 (RFC 7009 §2.2), so there is no status to
 * branch on and none is read.
 */
export async function signOut(): Promise<void> {
  try {
    await globalThis.fetch(`${API_BASE_URL}${REVOKE_PATH}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      credentials: "include",
      body: JSON.stringify({}),
    });
  } finally {
    clearSession();
  }
}

/** Test seam: drop any promise a previous case left in flight. */
export function resetRefreshForTests(): void {
  inFlight = null;
}

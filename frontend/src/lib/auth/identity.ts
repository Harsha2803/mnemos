/**
 * `GET /auth/me` — who the API says the bearer of this token is.
 *
 * Every field comes from the database on the request that asks, not from the
 * token: the access token carries `sub`, `org`, `sid` and nothing else, so
 * there is no email in it to render and no role in it to trust. That is the
 * point of the design and not an inconvenience — it is what makes a revoked
 * role take effect on the next call.
 *
 * The generated client is used rather than a bare `fetch`, so a renamed
 * endpoint or a changed field is a compile error here instead of `undefined` in
 * the sidebar.
 */

import { api } from "@/lib/api/client";
import type { Identity } from "@/lib/auth/session";

export async function fetchIdentity(signal?: AbortSignal): Promise<Identity | null> {
  const { data, response } = await api.GET("/api/v1/auth/me", { signal });

  // 401 is an answer — "you are not signed in" — and the fetch layer has
  // already tried a refresh by the time it reaches here. Throwing would make
  // the ordinary signed-out case indistinguishable from the API being down.
  if (response.status === 401) return null;
  if (!response.ok || data === undefined) {
    throw new Error(`could not read the current principal: HTTP ${response.status}`);
  }
  return data;
}

import createClient from "openapi-fetch";

import { getAccessToken } from "@/lib/auth/session";

import type { paths } from "./schema";

/**
 * Inlined into the browser bundle at build time, which is why the Dockerfile
 * takes it as a build argument and not only as container environment. The
 * fallback is the compose stack's own address, so `npm run dev` against a local
 * API needs no configuration at all.
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * The paths that must never be retried after a refresh.
 *
 * `/auth/token` *is* the refresh, so retrying it after refreshing would present
 * the rotated credential a second time — which the backend reads as theft and
 * answers by revoking the whole family. That is the self-inflicted sign-out this
 * layer exists to prevent, arriving through a door the single-flight guard does
 * not cover.
 */
const NEVER_RETRIED: readonly string[] = [
  "/api/v1/auth/token",
  "/api/v1/auth/token:revoke",
];

/**
 * `fetch`, with the access token attached and **one** retry after a refresh.
 *
 * TanStack Query has no interceptor — it calls whatever function a query hands
 * it — so the seam belongs here, underneath every call the app makes, rather
 * than in a place each new query has to remember to opt into.
 *
 * The rules, in the order they matter:
 *
 * 1. A 401 triggers **one** refresh, collapsed across every in-flight request by
 *    `refreshAccessToken`. Rotation treats a second concurrent presentation of a
 *    refresh token as theft, so N requests refreshing N times is a client that
 *    signs itself out.
 * 2. A second 401 after a successful refresh is not a stale token — it is a
 *    genuine denial, and it is returned rather than retried again. `session.ts`
 *    has already been cleared by then if the refresh failed, and the auth
 *    boundary sends the user back to sign-in.
 * 3. The request is cloned *before* the first attempt. A `Request` body is a
 *    stream that can be read once; retrying the original would send an empty
 *    body and turn a recoverable 401 into a baffling 422.
 */
async function authenticatedFetch(request: Request): Promise<Response> {
  const path = new URL(request.url).pathname;
  const spare = NEVER_RETRIED.includes(path) ? null : request.clone();

  const first = await globalThis.fetch(withBearer(request));
  if (first.status !== 401 || spare === null) return first;

  // Imported lazily so `refresh.ts` can name this module for `API_BASE_URL`
  // without a cycle at module-evaluation time.
  const { refreshAccessToken } = await import("@/lib/auth/refresh");
  const token = await refreshAccessToken();
  if (token === null) return first;

  return globalThis.fetch(withBearer(spare, token));
}

function withBearer(request: Request, token: string | null = getAccessToken()): Request {
  if (token === null) return request;
  const headers = new Headers(request.headers);
  headers.set("Authorization", `Bearer ${token}`);
  return new Request(request, { headers });
}

/**
 * The API client, typed from `schema.ts` — which is generated from the running
 * backend's `/openapi.json` and committed, never hand-edited.
 *
 * The point is not convenience. A hand-maintained TypeScript interface
 * mirroring a Pydantic model is a second source of truth that drifts silently,
 * and the drift surfaces as a runtime error in front of a user rather than as a
 * red build (DesignSystem §5). Here, a renamed endpoint is a compile error at
 * every call site.
 */
export const api = createClient<paths>({
  baseUrl: API_BASE_URL,
  // openapi-fetch captures its `fetch` when the client is built, and the client
  // is a module singleton — so the wrapper is installed once, here, and every
  // call the app will ever make goes through it. It reaches `globalThis.fetch`
  // at the moment of each call rather than capturing it, which is what keeps a
  // test stub effective.
  fetch: authenticatedFetch,
});

import createClient from "openapi-fetch";

import type { paths } from "./schema";

/**
 * Inlined into the browser bundle at build time, which is why the Dockerfile
 * takes it as a build argument and not only as container environment. The
 * fallback is the compose stack's own address, so `npm run dev` against a local
 * API needs no configuration at all.
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  // openapi-fetch captures `globalThis.fetch` when the client is built, and the
  // client is a module singleton. Going through the global on every call means
  // anything installed afterwards is honoured — a test stub today, and the
  // 401-refresh wrapper M3.4 needs tomorrow.
  fetch: (request) => globalThis.fetch(request),
});

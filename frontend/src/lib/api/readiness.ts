import { api } from "./client";

export type DependencyCheck = {
  /** `postgres`, `redis`, … — whatever the API reports, not a fixed list. */
  name: string;
  ok: boolean;
  /** The API's own word for the state, shown verbatim when it is not "ok". */
  detail: string;
};

export type Readiness = {
  ready: boolean;
  checks: readonly DependencyCheck[];
};

/**
 * Narrow `/readyz`'s body at runtime.
 *
 * The endpoint returns a bare `JSONResponse`, so the API publishes it with an
 * empty response schema and `openapi-typescript` correctly generates `unknown`.
 * This function is *not* a hand-written mirror of a Pydantic model — there is no
 * model to mirror — it is the validation that has to happen somewhere once the
 * generator has honestly said "the server does not describe this".
 *
 * It throws rather than guessing. A shape it does not recognise means the
 * contract moved, and "unreachable" on screen is the truthful rendering of
 * that; quietly coercing it would show a green light for a payload nobody
 * understands. The real fix is a response model on the backend, which belongs
 * to the next task that touches Python — TRACKER §4.
 */
export function parseReadiness(payload: unknown): Readiness {
  if (typeof payload !== "object" || payload === null) {
    throw new TypeError("readiness payload is not an object");
  }

  const body = payload as Record<string, unknown>;
  const status = body["status"];
  const checks = body["checks"];

  if (status !== "ready" && status !== "not_ready") {
    throw new TypeError(`readiness payload has an unrecognised status: ${String(status)}`);
  }
  if (typeof checks !== "object" || checks === null || Array.isArray(checks)) {
    throw new TypeError("readiness payload has no checks object");
  }

  const parsed: DependencyCheck[] = Object.entries(checks as Record<string, unknown>).map(
    ([name, detail]) => ({
      name,
      ok: detail === "ok",
      detail: typeof detail === "string" ? detail : "unknown",
    }),
  );

  return { ready: status === "ready", checks: parsed };
}

/**
 * One real call, end to end: the generated client, the running API's CORS
 * configuration, and the browser, all exercised at once. Each of the three
 * works alone; this is what proves they work together.
 */
export async function fetchReadiness(signal?: AbortSignal): Promise<Readiness> {
  // `"/readyz"` is checked against the generated `paths`, so a moved or renamed
  // endpoint is a compile error here rather than a 404 in front of a user.
  const { data, error, response } = await api.GET("/readyz", { signal });

  // A degraded API answers 503 with the same body, which openapi-fetch routes
  // to `error`. That is a real answer about readiness, not a transport failure,
  // so it is parsed rather than thrown away.
  const payload = response.ok ? data : error;
  return parseReadiness(payload);
}

import { vi } from "vitest";

/**
 * A `fetch` double that routes by path, and records what it was asked.
 *
 * `stubJsonResponse` answers everything with one body, which was right when the
 * app made one call. From A0 a single user action produces several — the
 * request, the refresh it triggers, the retry — and the interesting assertions
 * are about *which* endpoint was called and *how many times*, so the double has
 * to know the difference.
 *
 * It accepts both call shapes deliberately: `openapi-fetch` hands us a
 * `Request`, while `refresh.ts` calls `fetch(url, init)` directly. A double that
 * only understood one of them would silently miss half the traffic.
 */
export type Handler = (call: RecordedCall) => Promise<Response> | Response;

export type RecordedCall = {
  url: URL;
  path: string;
  method: string;
  headers: Headers;
  credentials: RequestCredentials | undefined;
};

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

/** The API's one denial. Identical for every cause, by construction. */
export const DENIAL = { error: { code: "unauthenticated", message: "authentication failed" } };

export function stubRouter(handler: Handler) {
  const calls: RecordedCall[] = [];

  const fetchMock = vi.fn(async (input: unknown, init?: RequestInit) => {
    const call = describe(input, init);
    calls.push(call);
    return handler(call);
  });

  vi.stubGlobal("fetch", fetchMock);
  return {
    calls,
    /** How many times a given path was requested, whatever the method. */
    countOf: (path: string) => calls.filter((call) => call.path === path).length,
  };
}

function describe(input: unknown, init?: RequestInit): RecordedCall {
  if (input instanceof Request) {
    return {
      url: new URL(input.url),
      path: new URL(input.url).pathname,
      method: input.method,
      headers: new Headers(input.headers),
      credentials: input.credentials,
    };
  }
  const url = new URL(String(input));
  return {
    url,
    path: url.pathname,
    method: init?.method ?? "GET",
    headers: new Headers(init?.headers),
    credentials: init?.credentials,
  };
}

/** A promise somebody else resolves — for holding a response open on purpose. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

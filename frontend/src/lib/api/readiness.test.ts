import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "./client";
import { fetchReadiness, parseReadiness } from "./readiness";

function respondWith(status: number, body: unknown) {
  const fetchMock = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("readiness", () => {
  it("test_a_ready_response_lists_every_dependency_the_api_reports", async () => {
    // The check names are not hard-coded on this side. The API decides what it
    // depends on; a frontend with its own fixed list goes stale the moment a
    // dependency is added and shows a green light for something it stopped
    // asking about.
    const fetchMock = respondWith(200, {
      status: "ready",
      checks: { postgres: "ok", redis: "ok" },
    });

    const readiness = await fetchReadiness();

    expect(readiness.ready).toBe(true);
    expect(readiness.checks).toEqual([
      { name: "postgres", ok: true, detail: "ok" },
      { name: "redis", ok: true, detail: "ok" },
    ]);

    const [url] = fetchMock.mock.calls[0] as unknown as [Request | string];
    const requested = typeof url === "string" ? url : url.url;
    expect(requested).toBe(`${API_BASE_URL}/readyz`);
  });

  it("test_a_503_is_read_as_an_answer_about_readiness_not_as_a_failure", async () => {
    // `/readyz` answers 503 with the same body when a dependency is down. That
    // is the endpoint working, not the endpoint failing, and throwing it away
    // would turn "redis is down" into "the API is unreachable" — which sends
    // whoever reads it looking in the wrong place.
    respondWith(503, {
      status: "not_ready",
      checks: { postgres: "ok", redis: "error: ConnectionError" },
    });

    const readiness = await fetchReadiness();

    expect(readiness.ready).toBe(false);
    expect(readiness.checks).toContainEqual({
      name: "redis",
      ok: false,
      detail: "error: ConnectionError",
    });
  });

  it("test_an_unrecognised_payload_is_rejected_rather_than_coerced", () => {
    // The generator says `unknown` for this endpoint because the API publishes
    // no schema for it, so the narrowing has to be real. Coercing an unknown
    // shape would put a green light next to a payload nobody understands.
    expect(() => parseReadiness(null)).toThrow(TypeError);
    expect(() => parseReadiness({ status: "fine" })).toThrow(/unrecognised status/);
    expect(() => parseReadiness({ status: "ready" })).toThrow(/no checks object/);
    expect(() => parseReadiness({ status: "ready", checks: ["postgres"] })).toThrow(
      /no checks object/,
    );
  });

  it("test_a_non_string_check_value_is_reported_rather_than_treated_as_ok", () => {
    // `ok` is `detail === "ok"`, so anything unexpected lands on the failing
    // side. The dangerous direction is the other one.
    const readiness = parseReadiness({ status: "ready", checks: { postgres: 1 } });
    expect(readiness.checks).toEqual([{ name: "postgres", ok: false, detail: "unknown" }]);
  });
});

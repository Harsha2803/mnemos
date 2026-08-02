import { describe, expect, it, vi } from "vitest";

import { API_BASE_URL } from "@/lib/api/client";
import { jsonResponse, stubRouter } from "@/test/http";

/**
 * The suite is offline, and this is the test that keeps it that way.
 *
 * It exists because of a real failure: 74 tests passed and the run still exited
 * 1, on `connect ECONNREFUSED ::1:8000`. A component test had stubbed `fetch`,
 * unstubbed it in `afterEach`, and left the session bootstrap's async chain
 * still running — and the next thing that chain did was reach the network. On a
 * development machine that request lands on whichever API container happens to
 * be up and nothing looks wrong. CI has nothing on :8000, so CI found it.
 *
 * `vitest.setup.ts` therefore assigns `globalThis.fetch` before any test runs,
 * which is also what `vi.unstubAllGlobals()` restores. Without these
 * assertions that arrangement is invisible and one refactor from being undone.
 */
describe("the test suite never reaches the network", () => {
  it("test_an_unstubbed_fetch_answers_401_instead_of_dialling_the_api", async () => {
    const response = await fetch(`${API_BASE_URL}/api/v1/auth/me`);

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({
      error: { code: "unauthenticated", message: "authentication failed" },
    });
  });

  it("test_unstubbing_restores_the_offline_default_and_not_the_real_fetch", async () => {
    // The half that actually matters. `vi.stubGlobal` remembers whatever was
    // there when it first ran, so the offline default has to be installed before
    // any test stubs anything — otherwise unstubbing hands the real `fetch` back
    // and the leak returns through the same door it came in.
    stubRouter(() => jsonResponse(200, { stubbed: true }));
    expect((await fetch(`${API_BASE_URL}/readyz`)).status).toBe(200);

    vi.unstubAllGlobals();

    expect((await fetch(`${API_BASE_URL}/readyz`)).status).toBe(401);
  });
});

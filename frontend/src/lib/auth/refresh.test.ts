import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchIdentity } from "@/lib/auth/identity";
import { ME_PATH, REVOKE_PATH, TOKEN_PATH, refreshAccessToken, signOut } from "@/lib/auth/refresh";
import { getAccessToken, getSessionSnapshot, setAccessToken } from "@/lib/auth/session";
import { DENIAL, deferred, jsonResponse, stubRouter } from "@/test/http";

afterEach(() => {
  vi.unstubAllGlobals();
});

const IDENTITY = {
  user_id: "018f-user",
  email: "admin@mnemos.local",
  display_name: "Ada Admin",
  org_id: "018f-org",
  org_slug: "mnemos",
  session_id: "018f-session",
  permissions: ["*:*"],
  tags: [],
};

function tokenBody(access_token: string) {
  return { access_token, token_type: "Bearer", expires_in: 900, org_slug: "mnemos" };
}

describe("collapsing concurrent refreshes", () => {
  it("test_concurrent_401s_trigger_exactly_one_refresh", async () => {
    /**
     * The test this whole module exists for, and it is correctness rather than
     * efficiency.
     *
     * Every use of a refresh token rotates it, and presenting a token whose row
     * already names a successor is treated by the API as *proof* of theft — the
     * legitimate holder and a thief cannot both hold the current token — so the
     * entire chain is revoked. Losing the compare-and-set counts as the same
     * evidence. A client that answers five 401s with five refreshes therefore
     * signs itself out: one wins, four look like a replayed credential.
     *
     * The refresh response is held open until every request has arrived at it,
     * so this asserts the collapse rather than accidentally observing that the
     * first refresh happened to finish before the second request started.
     */
    const gate = deferred<void>();
    let served = 0;

    const router = stubRouter(async (call) => {
      if (call.path === TOKEN_PATH) {
        await gate.promise;
        return jsonResponse(200, tokenBody("fresh-access-token"));
      }
      // The first five hits are stale-token 401s; everything after the refresh
      // succeeds. A stub that answered 401 forever would prove nothing about
      // the retry.
      served += 1;
      return served <= 5 ? jsonResponse(401, DENIAL) : jsonResponse(200, IDENTITY);
    });

    setAccessToken("expired-access-token");
    const inFlight = Promise.all(Array.from({ length: 5 }, () => fetchIdentity()));

    // Let all five 401s land and reach the refresh before it is allowed to
    // answer. A macrotask, not a microtask: the retry path crosses a dynamic
    // import and two `await`s.
    await new Promise((resolve) => setTimeout(resolve, 20));
    gate.resolve();

    const identities = await inFlight;

    expect(router.countOf(TOKEN_PATH)).toBe(1);
    expect(identities).toHaveLength(5);
    expect(identities.every((identity) => identity?.email === "admin@mnemos.local")).toBe(true);
    // Five original attempts plus five retries — the retry is what makes the
    // single refresh useful rather than merely cheap.
    expect(router.countOf(ME_PATH)).toBe(10);
  });

  it("test_the_refreshed_token_is_attached_to_the_retry", async () => {
    // Without this, the collapse above would be satisfied by a client that
    // refreshed once and then retried with the token it already knew was stale.
    const router = stubRouter((call) => {
      if (call.path === TOKEN_PATH) return jsonResponse(200, tokenBody("fresh-access-token"));
      return call.headers.get("Authorization") === "Bearer fresh-access-token"
        ? jsonResponse(200, IDENTITY)
        : jsonResponse(401, DENIAL);
    });

    setAccessToken("expired-access-token");

    expect(await fetchIdentity()).toEqual(IDENTITY);
    expect(router.countOf(TOKEN_PATH)).toBe(1);
  });

  it("test_a_second_401_after_a_successful_refresh_is_not_retried_again", async () => {
    // A genuine denial — a revoked session, a deactivated user — must not become
    // an infinite retry loop against an API that has already said no twice.
    const router = stubRouter((call) =>
      call.path === TOKEN_PATH
        ? jsonResponse(200, tokenBody("fresh-access-token"))
        : jsonResponse(401, DENIAL),
    );

    setAccessToken("expired-access-token");

    expect(await fetchIdentity()).toBeNull();
    expect(router.countOf(TOKEN_PATH)).toBe(1);
    expect(router.countOf(ME_PATH)).toBe(2);
  });

  it("test_a_failed_refresh_clears_the_session_and_returns_to_anonymous", async () => {
    stubRouter((call) =>
      call.path === TOKEN_PATH ? jsonResponse(401, DENIAL) : jsonResponse(401, DENIAL),
    );

    setAccessToken("expired-access-token");
    expect(getSessionSnapshot().status).toBe("authenticated");

    expect(await refreshAccessToken()).toBeNull();

    expect(getSessionSnapshot().status).toBe("anonymous");
    expect(getAccessToken()).toBeNull();
  });

  it("test_an_unreachable_api_does_not_sign_the_user_out", async () => {
    // A laptop that slept is not a revoked session. Treating a transport
    // failure as a denial is how an app logs people out on every tunnel.
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    setAccessToken("a-live-access-token");

    expect(await refreshAccessToken()).toBeNull();

    expect(getSessionSnapshot().status).toBe("authenticated");
  });

  it("test_the_refresh_call_sends_the_cookie", async () => {
    // The refresh token is `httpOnly` and cross-origin, so nothing is sent
    // without `credentials: "include"`. Its absence is the single most common
    // reason a refresh that looks correct returns 401 forever.
    const router = stubRouter(() => jsonResponse(200, tokenBody("fresh-access-token")));

    await refreshAccessToken();

    const call = router.calls.find((each) => each.path === TOKEN_PATH);
    expect(call?.method).toBe("POST");
    expect(call?.credentials).toBe("include");
  });

  it("test_the_refresh_endpoint_is_never_itself_retried_after_a_401", async () => {
    /**
     * The door the single-flight guard does not cover.
     *
     * If the generic retry applied to `/auth/token`, a 401 from a refresh would
     * trigger a refresh, whose response would be replayed against a chain that
     * has already rotated — which the API reads as theft and answers by killing
     * the family. So this path is excluded by name, and this is the test that
     * would notice the exclusion being tidied away.
     */
    const router = stubRouter(() => jsonResponse(401, DENIAL));

    expect(await refreshAccessToken()).toBeNull();

    expect(router.countOf(TOKEN_PATH)).toBe(1);
  });
});

describe("signing out", () => {
  it("test_signout_revokes_the_refresh_family_and_clears_the_cookie", async () => {
    /**
     * The client half. `POST /auth/token:revoke` is what kills the whole
     * rotation chain and clears the cookie — both server-side, and both asserted
     * on the wire in `backend/tests/test_auth_endpoints.py`
     * (`test_revoke_clears_the_cookie_and_kills_the_session`), because a
     * `httpOnly` cookie is by definition not observable from here.
     *
     * What is observable here, and what this asserts, is that the call is made
     * at all, that it carries the cookie (`credentials: "include"` — without it
     * the browser sends nothing and the server revokes nothing), and that the
     * in-memory token is dropped afterwards. A client that cleared only its own
     * state would *look* signed out and be one reload from proving itself wrong.
     */
    const router = stubRouter(() => new Response(null, { status: 204 }));
    setAccessToken("a-live-access-token");

    await signOut();

    const call = router.calls.find((each) => each.path === REVOKE_PATH);
    expect(call?.method).toBe("POST");
    expect(call?.credentials).toBe("include");
    expect(getAccessToken()).toBeNull();
    expect(getSessionSnapshot().status).toBe("anonymous");
  });

  it("test_signout_clears_local_state_even_when_the_api_is_unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    setAccessToken("a-live-access-token");

    await expect(signOut()).rejects.toThrow();

    expect(getAccessToken()).toBeNull();
  });
});

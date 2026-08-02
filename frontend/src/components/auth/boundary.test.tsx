import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { AppShell } from "@/components/shell/AppShell";
import { INSPECTOR_INLINE, SIDEBAR_INLINE } from "@/components/shell/useMediaQuery";
import { setMediaQueries } from "@/test/harness";
import { ME_PATH, REVOKE_PATH, TOKEN_PATH } from "@/lib/auth/refresh";
import { RETURN_TO_KEY } from "@/lib/auth/destination";
import { DENIAL, jsonResponse, stubRouter } from "@/test/http";
import { navigation, visit } from "@/test/navigation";
import { renderWithProviders } from "@/test/render";

import { AuthBoundary } from "./AuthBoundary";
import { SignInComplete } from "./SignInComplete";

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

/** A stack that recognises the session in the `httpOnly` cookie. */
function stubSignedIn() {
  return stubRouter((call) => {
    if (call.path === TOKEN_PATH) {
      return jsonResponse(200, {
        access_token: "a-live-access-token",
        token_type: "Bearer",
        expires_in: 900,
        org_slug: "mnemos",
      });
    }
    if (call.path === ME_PATH) return jsonResponse(200, IDENTITY);
    if (call.path === REVOKE_PATH) return new Response(null, { status: 204 });
    return jsonResponse(200, { status: "ready", checks: { postgres: "ok", redis: "ok" } });
  });
}

/** A stack with no session: the refresh cookie is absent, expired or revoked. */
function stubSignedOut() {
  return stubRouter((call) =>
    call.path === TOKEN_PATH || call.path === ME_PATH
      ? jsonResponse(401, DENIAL)
      : jsonResponse(200, { status: "ready", checks: { postgres: "ok", redis: "ok" } }),
  );
}

describe("the auth boundary", () => {
  it("test_an_unauthenticated_visit_redirects_to_signin_preserving_the_destination", async () => {
    /**
     * Somebody who followed a link to a specific screen, signed in, and landed
     * on the home page has been made to navigate twice for no reason — and by
     * the second time they frequently cannot remember what the link was.
     *
     * This is a courtesy and never the control. The API authenticates every
     * route by default; a user who defeats this component by editing their own
     * JavaScript reaches a shell whose every call answers 401.
     */
    stubSignedOut();
    visit("/knowledge");

    renderWithProviders(
      <AuthBoundary>
        <p>the protected shell</p>
      </AuthBoundary>,
    );

    await waitFor(() => {
      expect(navigation.replace).toHaveBeenCalledWith("/signin?next=%2Fknowledge");
    });
    expect(screen.queryByText("the protected shell")).not.toBeInTheDocument();
  });

  it("test_a_signed_in_visit_renders_the_shell", async () => {
    // The control. A boundary that redirected everybody would pass the test
    // above and would be an application nobody can reach.
    stubSignedIn();

    renderWithProviders(
      <AuthBoundary>
        <p>the protected shell</p>
      </AuthBoundary>,
    );

    expect(await screen.findByText("the protected shell")).toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();
  });

  it("test_the_pending_boundary_shows_a_skeleton_and_not_a_spinner_over_a_blank_region", () => {
    // DesignSystem §4. A spinner discards the layout information the user is
    // about to need, and one region gets one label rather than each shape
    // announcing itself.
    stubSignedIn();

    renderWithProviders(
      <AuthBoundary>
        <p>the protected shell</p>
      </AuthBoundary>,
    );

    expect(screen.getByRole("status", { name: "Checking your session" })).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("test_the_session_survives_a_reload_by_exchanging_the_cookie", async () => {
    /**
     * The access token lives in a module variable, so a reload loses it. What
     * survives is the `httpOnly` cookie, and the app's first act is to exchange
     * it — the same call a 401 makes later, which is why "stay signed in across
     * a reload" and "recover from an expired token" cannot drift apart.
     *
     * A fresh render *is* a reload from the module's point of view: `session.ts`
     * is reset between tests.
     */
    const router = stubSignedIn();

    renderWithProviders(
      <AuthBoundary>
        <p>the protected shell</p>
      </AuthBoundary>,
    );

    expect(await screen.findByText("the protected shell")).toBeInTheDocument();
    // Once, not once per component that wanted a session.
    expect(router.countOf(TOKEN_PATH)).toBe(1);
  });

  it("test_the_boundary_has_no_axe_violations_while_it_is_waiting", async () => {
    stubSignedIn();

    const { container } = renderWithProviders(
      <AuthBoundary>
        <p>the protected shell</p>
      </AuthBoundary>,
    );

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

describe("returning from Keycloak", () => {
  it("test_the_completion_screen_sends_the_user_to_where_they_were_headed", async () => {
    stubSignedIn();
    window.sessionStorage.setItem(RETURN_TO_KEY, "/knowledge");

    renderWithProviders(<SignInComplete />);

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/knowledge"));
    // Single-use, like the OIDC state it rode alongside: a destination that
    // outlived its login would hijack the *next* sign-in.
    expect(window.sessionStorage.getItem(RETURN_TO_KEY)).toBeNull();
  });

  it("test_the_completion_screen_falls_back_to_the_home_page", async () => {
    stubSignedIn();

    renderWithProviders(<SignInComplete />);

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/"));
  });

  it("test_a_callback_that_produced_no_session_returns_to_signin", async () => {
    // Somebody who navigated here by hand, or a cookie the API refused.
    stubSignedOut();

    renderWithProviders(<SignInComplete />);

    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/signin"));
  });
});

describe("the signed-in shell", () => {
  // A desktop viewport, so the sidebar is an inline column rather than a closed
  // sheet — below 768px it is a Radix Dialog and its contents are not in the
  // document at all until it is opened.
  beforeEach(() => {
    setMediaQueries({ [INSPECTOR_INLINE]: true, [SIDEBAR_INLINE]: true });
  });

  it("test_the_sidebar_names_the_signed_in_user_and_their_org", async () => {
    /**
     * The shell rendered a placeholder here until now. Both values come from
     * `GET /auth/me` — the access token carries no email and no org slug, by
     * design — so this is also the frontend's proof that the guard's hydration
     * reaches the screen.
     *
     * The org is shown as well as the email because every row in this
     * application is scoped to one tenant, and somebody with access to two can
     * otherwise read the wrong one's numbers for a long time before anything
     * looks wrong.
     */
    stubSignedIn();

    renderWithProviders(
      <AppShell>
        <h1>Overview</h1>
      </AppShell>,
    );

    expect(await screen.findByText("admin@mnemos.local")).toBeInTheDocument();
    expect(screen.getByText("mnemos")).toBeInTheDocument();
  });

  it("test_signing_out_from_the_sidebar_revokes_and_returns_to_signin", async () => {
    const router = stubSignedIn();

    renderWithProviders(
      <AppShell>
        <h1>Overview</h1>
      </AppShell>,
    );
    await screen.findByText("admin@mnemos.local");

    // Named for the tenant being left, not a bare "Sign out": somebody signed
    // in to two workspaces in two tabs should not have to guess which one this
    // is (DesignSystem §4, destructive actions name their object).
    await userEvent.click(screen.getByRole("button", { name: "Sign out of mnemos" }));

    await waitFor(() => expect(router.countOf(REVOKE_PATH)).toBe(1));
    await waitFor(() => expect(navigation.replace).toHaveBeenCalledWith("/signin"));
  });

  it("test_the_signed_in_shell_has_no_axe_violations", async () => {
    stubSignedIn();

    const { container } = renderWithProviders(
      <AppShell>
        <h1>Overview</h1>
      </AppShell>,
    );
    await screen.findByText("admin@mnemos.local");

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });
});

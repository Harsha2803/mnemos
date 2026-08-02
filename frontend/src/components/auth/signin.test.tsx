import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { API_BASE_URL } from "@/lib/api/client";
import { RETURN_TO_KEY } from "@/lib/auth/destination";
import { navigation, visit } from "@/test/navigation";

import { AUTHORIZE_PATH, SignInForm } from "./SignInForm";

/**
 * `window.location.assign` is a no-op in jsdom and logs "Not implemented", so
 * it is replaced with a recorder. Asserting on it is asserting on the whole
 * mechanism: this form navigates rather than fetching, because `authorize`
 * answers with a redirect to an identity provider and a cross-origin `fetch`
 * can neither read a `Location` header nor follow one into a login form.
 */
function captureNavigation() {
  const assign = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...window.location, assign },
  });
  return assign;
}

let assign: ReturnType<typeof captureNavigation>;

beforeEach(() => {
  assign = captureNavigation();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("the sign-in screen", () => {
  it("test_signin_error_is_identical_for_unknown_org_and_denied_login", async () => {
    /**
     * **The acceptance test, and it asserts the rendered text.**
     *
     * The API already guarantees one constant on the wire — an unknown org, a
     * disabled provider, a cancelled Keycloak login and a refused provisioning
     * all redirect back here with the same `error=auth_failed`, asserted in
     * `backend/tests/test_auth_endpoints.py::test_every_login_failure_produces
     * _the_same_url`. This is the layer that could undo it, by reading a signal
     * and saying "no such organisation" — which is exactly the M3.2a mistake one
     * layer further out, and hands back the tenant enumeration the backend spent
     * two milestones closing.
     *
     * So the two cases below are handed *different* signals on purpose. The
     * screen must not care. If someone later adds `if (error === "unknown_org")`
     * this fails, which is the whole reason it is written against two values the
     * API does not currently emit rather than against the one it does.
     */
    visit("/signin", "error=unknown_org");
    const { unmount } = render(<SignInForm />);
    const unknownOrg = screen.getByRole("alert").textContent;
    unmount();

    visit("/signin", "error=access_denied");
    render(<SignInForm />);
    const deniedLogin = screen.getByRole("alert").textContent;

    expect(unknownOrg).toBe(deniedLogin);
    expect(unknownOrg).not.toBe("");
    // Neither message may name what went wrong. Belt and braces: however the
    // copy is later reworded, it must not acquire a specific cause.
    for (const leak of ["organisation not found", "no such", "unknown", "denied", "does not exist"]) {
      expect(unknownOrg?.toLowerCase()).not.toContain(leak);
    }
  });

  it("test_the_error_region_is_live_and_present_before_it_has_anything_to_say", () => {
    // A live region added to the page at the moment it gains content is a region
    // many screen readers never announce: they build their model of the page up
    // front and only watch the regions that existed then.
    visit("/signin");
    render(<SignInForm />);

    const region = document.getElementById("signin-error");
    expect(region).toHaveAttribute("aria-live", "polite");
    expect(region).toHaveTextContent("");
  });

  it("test_submitting_the_form_drives_the_authorize_endpoint_with_the_org", async () => {
    visit("/signin");
    render(<SignInForm />);

    await userEvent.type(screen.getByLabelText("Workspace"), "  mnemos  ");
    await userEvent.click(screen.getByRole("button", { name: /continue with keycloak/i }));

    // Trimmed: a slug pasted with a trailing space is the same tenant, and
    // sending it verbatim would produce the constant denial with no clue why.
    expect(assign).toHaveBeenCalledWith(`${API_BASE_URL}${AUTHORIZE_PATH}?org=mnemos`);
  });

  it("test_pressing_enter_in_the_field_submits_the_form", async () => {
    // Real `<form>` semantics rather than a click handler on a div: Enter has
    // to work, because that is how most people finish a single-field form.
    visit("/signin");
    render(<SignInForm />);

    await userEvent.type(screen.getByLabelText("Workspace"), "mnemos{Enter}");

    expect(assign).toHaveBeenCalledTimes(1);
  });

  it("test_an_empty_workspace_does_not_navigate", async () => {
    visit("/signin");
    render(<SignInForm />);

    await userEvent.click(screen.getByRole("button", { name: /continue with keycloak/i }));

    expect(assign).not.toHaveBeenCalled();
  });

  it("test_the_intended_destination_survives_the_round_trip_through_keycloak", async () => {
    // The OIDC redirect URI is registered in the realm and cannot carry a
    // per-login parameter of ours, so the destination is stashed in this tab's
    // own storage. It is a path and not a credential — see `destination.ts`.
    visit("/signin", "next=%2Fknowledge");
    render(<SignInForm />);

    await userEvent.type(screen.getByLabelText("Workspace"), "mnemos{Enter}");

    expect(window.sessionStorage.getItem(RETURN_TO_KEY)).toBe("/knowledge");
  });

  it("test_an_off_origin_destination_is_refused", async () => {
    // `sessionStorage` is writable by any script on this origin and `next` comes
    // straight off the URL, so the stored value is a redirect target an attacker
    // would like to choose. `//evil.test` passes `startsWith("/")` and resolves
    // off-origin, which is the case a naive check misses.
    visit("/signin", "next=%2F%2Fevil.test");
    render(<SignInForm />);

    await userEvent.type(screen.getByLabelText("Workspace"), "mnemos{Enter}");

    expect(window.sessionStorage.getItem(RETURN_TO_KEY)).toBeNull();
  });

  it("test_there_is_exactly_one_primary_action_on_the_screen", () => {
    // DesignSystem §4: three ranks, and one `filled` per view. A second primary
    // button does not add emphasis, it removes it from the first.
    visit("/signin");
    render(<SignInForm />);

    const filled = screen
      .getAllByRole("button")
      .filter((button) => button.className.includes("bg-accent "));

    expect(filled).toHaveLength(1);
    expect(filled[0]).toHaveAccessibleName(/continue with keycloak/i);
  });

  it("test_the_signin_screen_has_no_axe_violations", async () => {
    visit("/signin", "error=auth_failed");
    const { container } = render(<SignInForm />);

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("test_the_signin_screen_is_not_wrapped_in_the_app_shell", () => {
    // The one screen that must render for somebody with no session. A sign-in
    // form inside a sidebar full of destinations they cannot reach is a screen
    // arguing with itself — and every one of those destinations would 401.
    visit("/signin");
    render(<SignInForm />);

    expect(screen.queryByRole("navigation", { name: "Workspace" })).not.toBeInTheDocument();
    expect(navigation.replace).not.toHaveBeenCalled();
  });
});

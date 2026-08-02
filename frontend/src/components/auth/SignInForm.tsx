"use client";

import { KeyRound } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { API_BASE_URL } from "@/lib/api/client";
import { isSafeDestination, rememberDestination } from "@/lib/auth/destination";

export const AUTHORIZE_PATH = "/api/v1/auth/oidc/authorize";

/**
 * The one message a failed sign-in ever shows.
 *
 * **Every failure renders this, and nothing branches to make it more
 * specific.** The API already guarantees a single constant on the wire — an
 * unknown org, a disabled provider, a cancelled login and a refused
 * provisioning all redirect here with the same flag — and a UI that inspected a
 * status code to say "no such organisation" would hand back the tenant
 * enumeration the backend spent M3.2 and M3.2a closing. That is the M3.2a
 * mistake one layer further out: a control tested (and enforced) one layer below
 * where it takes effect is not enforced.
 *
 * It is written to be *useful* without being *specific*: it names the two things
 * the person can actually check.
 */
export const SIGN_IN_ERROR =
  "We could not sign you in. Check the workspace name and try again, or ask your administrator whether your account has access.";

const ORG_FIELD = "org";

/**
 * Org slug, then Keycloak.
 *
 * A real `<form>` with a real `submit`, so Enter works, the browser can
 * autofill, and the field is genuinely associated with its label. The submit
 * navigates rather than fetching: `authorize` answers with a 307 to the identity
 * provider, and a cross-origin `fetch` cannot read a `Location` header it is not
 * allowed to see, let alone follow one into a login form.
 *
 * One `filled` button, because there is one primary action in this view
 * (DesignSystem §4 allows exactly three ranks and one primary).
 */
export function SignInForm() {
  const params = useSearchParams();
  const [org, setOrg] = useState("");

  const failed = params.get("error") !== null;
  const next = params.get("next");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const slug = org.trim();
    if (slug.length === 0) return;

    // A path, not a credential — see `destination.ts`. Stashed before the
    // navigation because the OIDC redirect URI is registered in the realm and
    // cannot carry a per-login parameter of ours.
    if (isSafeDestination(next)) rememberDestination(next);

    const url = new URL(AUTHORIZE_PATH, API_BASE_URL);
    url.searchParams.set(ORG_FIELD, slug);
    window.location.assign(url.toString());
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-bg-grouped px-6 py-12">
      <div className="flex w-full max-w-md flex-col gap-8">
        <header className="flex flex-col gap-2">
          <h1 className="text-large-title font-semibold tracking-title text-label">Mnemos</h1>
          <p className="text-callout leading-relaxed text-label-secondary">
            Sign in to your workspace. Authentication is handled by your
            organisation&rsquo;s identity provider.
          </p>
        </header>

        <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
          <div className="flex flex-col gap-2">
            <label htmlFor="org-slug" className="text-subheadline font-semibold text-label">
              Workspace
            </label>
            <input
              id="org-slug"
              name={ORG_FIELD}
              value={org}
              onChange={(event) => setOrg(event.target.value)}
              autoComplete="organization"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              required
              // `aria-describedby` binds the hint *and* the error region, so a
              // screen reader reads the failure as part of the field rather
              // than as a stray paragraph somewhere on the page.
              aria-describedby="org-slug-hint signin-error"
              className="hit-target rounded-md border border-separator bg-bg px-4 text-body text-label placeholder:text-label-tertiary focus-visible:border-accent"
              placeholder="acme"
            />
            <p id="org-slug-hint" className="text-footnote text-label-secondary">
              The short name in your workspace URL — <code className="font-mono">mnemos</code> on
              this development stack.
            </p>
          </div>

          {/*
            Always in the DOM, empty until there is something to say. A live
            region added to the page at the moment it gains content is a region
            many screen readers never announce, because they only watch the ones
            that existed when they built their model of the page.
          */}
          <p
            id="signin-error"
            role="alert"
            aria-live="polite"
            className="text-footnote text-danger empty:hidden"
          >
            {failed ? SIGN_IN_ERROR : ""}
          </p>

          <Button rank="filled" type="submit" className="w-full">
            <KeyRound className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />
            Continue with Keycloak
          </Button>
        </form>
      </div>
    </main>
  );
}

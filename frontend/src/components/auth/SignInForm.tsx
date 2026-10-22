"use client";

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
    <main className="grid min-h-dvh grid-cols-1 bg-bg lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
      {/* What Mnemos is, said once and shown once. The specimen is set in type,
          not an image: an answer with its source in the margin, and a fact
          revised rather than overwritten — the two things the product is for. */}
      <section
        aria-labelledby="signin-wordmark"
        className="flex flex-col justify-center gap-14 border-b border-separator bg-bg-secondary px-6 py-10 sm:px-12 lg:border-b-0 lg:border-r lg:py-16"
      >
        <div className="flex max-w-xl flex-col gap-4">
          <h1 id="signin-wordmark" className="font-serif text-large-title font-semibold tracking-title text-label">
            Mnemos
          </h1>
          <p className="font-serif text-title-3 leading-relaxed text-label">
            A workspace that answers from your documents and your data, and shows you where
            every answer came from.
          </p>
        </div>
        <Specimen />
      </section>

      <div className="flex items-center justify-center px-6 py-12 sm:px-12">
        <div className="flex w-full max-w-sm flex-col gap-8">
          <header className="flex flex-col gap-2">
            <h2 className="text-title-2 font-semibold tracking-title text-label">Sign in</h2>
            <p className="text-callout leading-relaxed text-label-secondary">
              Your organisation&rsquo;s identity provider handles the password. Mnemos only needs
              to know which workspace to open.
            </p>
          </header>

          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-2">
              <label htmlFor="org-slug" className="text-footnote font-semibold text-label-secondary">
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
                className="field hit-target font-mono"
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
              className="border-l-2 border-danger pl-3 text-footnote text-danger empty:hidden"
            >
              {failed ? SIGN_IN_ERROR : ""}
            </p>

            <Button rank="filled" type="submit" className="w-full">
              Continue with Keycloak
            </Button>
          </form>
        </div>
      </div>
    </main>
  );
}

/**
 * A few lines of the product, typeset: a cited answer with its sidenote, and a
 * claim revised. Decorative for assistive technology — the heading and the
 * sentence above already say what Mnemos is — so it is hidden from it.
 */
function Specimen() {
  return (
    <figure aria-hidden="true" className="hidden max-w-xl select-none flex-col gap-6 sm:flex">
      <div className="grid grid-cols-[minmax(0,1fr)_11rem] gap-6">
        <p className="font-serif text-reading leading-relaxed text-label">
          Under the 2026 handbook you can carry over up to three unused days into the next
          calendar year<sup className="citation-marker">1</sup>. The 2025 revision allowed five; it
          is superseded, so it was left out.
        </p>
        <p className="border-l-2 border-rubric pl-3 text-caption leading-snug text-label-secondary">
          <span className="font-semibold text-rubric">1</span>{" "}
          <span className="font-semibold text-label">Employee Handbook 2026</span>{" "}
          <span className="font-mono">p.4</span>
          <span className="mt-1 block font-serif text-footnote">
            “…a maximum of three (3) unused annual leave days…”
          </span>
        </p>
      </div>
      <p className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-footnote">
        <span className="font-mono text-caption uppercase tracking-caps text-label-secondary">Memory</span>
        <span className="text-label">Priya Raman · reports to</span>
        <del className="text-label-secondary decoration-rubric decoration-2">Elena Petrova</del>
        <span className="text-rubric">→</span>
        <ins className="rounded-sm bg-rubric-tint px-1 text-label no-underline">Jonas Weber</ins>
        <span className="font-mono text-caption text-label-secondary">effective 1 Jul 2026</span>
      </p>
    </figure>
  );
}

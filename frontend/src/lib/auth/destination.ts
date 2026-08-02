/**
 * Remembering where the user was going, across a round trip through Keycloak.
 *
 * The destination cannot ride on the URL: the OIDC redirect URI is registered
 * in the realm and must match byte-for-byte, and the API — not the browser —
 * decides where the callback sends people. So it is stashed in the tab's own
 * `sessionStorage` before the navigation and read back afterwards.
 *
 * **A path is not a credential.** This is the one thing in the auth flow that
 * may be written to web storage, and it is written precisely because it is
 * worthless to an attacker who has already got script execution. The access
 * token is not here and must never be — see `session.ts`.
 *
 * What *is* dangerous about a stored destination is that it is a redirect
 * target, and `sessionStorage` is writable by any script on this origin. So it
 * is validated on the way out rather than on the way in: only a same-document
 * path, never a scheme, never a host, never a protocol-relative `//evil.test`
 * (which a browser resolves as an absolute URL and which `startsWith("/")`
 * happily accepts).
 */

export const RETURN_TO_KEY = "mnemos.auth.returnTo";

export const SIGN_IN_PATH = "/signin";
export const SIGN_IN_COMPLETE_PATH = "/signin/complete";
export const DEFAULT_DESTINATION = "/";

/** Whether a string is a path this app may navigate to after signing in. */
export function isSafeDestination(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.startsWith("/") &&
    // `//evil.test` is protocol-relative and resolves off-origin.
    !value.startsWith("//") &&
    // A backslash is normalised to `/` by some browsers, so `/\evil.test` is
    // the same attack wearing a different character.
    !value.startsWith("/\\") &&
    !value.startsWith(SIGN_IN_PATH)
  );
}

export function rememberDestination(path: string): void {
  try {
    if (isSafeDestination(path)) window.sessionStorage.setItem(RETURN_TO_KEY, path);
  } catch {
    // `sessionStorage` throws outright in a partitioned or cookie-blocked
    // context. Losing the destination costs the user one click; throwing here
    // would cost them the sign-in.
  }
}

/** Read the stored destination and clear it. Single-use, like the OIDC state. */
export function takeDestination(): string {
  try {
    const stored = window.sessionStorage.getItem(RETURN_TO_KEY);
    window.sessionStorage.removeItem(RETURN_TO_KEY);
    return isSafeDestination(stored) ? stored : DEFAULT_DESTINATION;
  } catch {
    return DEFAULT_DESTINATION;
  }
}

/** The sign-in URL that will send the user back to where they were headed. */
export function signInHrefFor(pathname: string): string {
  return isSafeDestination(pathname)
    ? `${SIGN_IN_PATH}?next=${encodeURIComponent(pathname)}`
    : SIGN_IN_PATH;
}

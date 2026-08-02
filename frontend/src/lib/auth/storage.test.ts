import { readFileSync, readdirSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchIdentity } from "@/lib/auth/identity";
import { refreshAccessToken } from "@/lib/auth/refresh";
import { getAccessToken } from "@/lib/auth/session";
import { jsonResponse, stubRouter } from "@/test/http";

// Vitest runs with the cwd set to the Vite root, which is `frontend/` —
// `import.meta.url` is an http URL under jsdom and cannot be turned into a path.
const SRC = resolve(process.cwd(), "src");

/**
 * The only files allowed to touch `localStorage` or `sessionStorage`, and what
 * each one is allowed to keep there.
 *
 * An allow-list rather than a blanket ban, because two things legitimately
 * belong in web storage and both are worthless to an attacker who already has
 * script execution: the theme preference, and the path the user was headed for
 * before signing in. Adding a third entry should be an argument somebody has to
 * win in review, which is what this test forces.
 */
const STORAGE_IS_ALLOWED: Record<string, string> = {
  "lib/theme.ts": "the theme preference — a word, chosen by the user, readable by anyone",
  "components/theme/useThemePreference.ts": "reads the same preference through the store",
  "lib/auth/destination.ts": "the post-login destination — a same-origin path, validated on read",
};

/** Generated from the API's OpenAPI document; its prose is not our code. */
const GENERATED = new Set(["lib/api/schema.ts"]);

const TOKEN = "a-live-access-token-that-must-never-be-persisted";

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return entry.name === "test" ? [] : sourceFiles(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

/**
 * Comments out, then look.
 *
 * Several of these modules *explain* why they do not use `localStorage`, and a
 * grep that counted the explanation as an offence would push the reasoning out
 * of the code — which is the opposite of what this repository wants. The rule is
 * about what the module does, so the test reads what the module does.
 */
function code(source: string): string {
  return source.replaceAll(/\/\*[\s\S]*?\*\//g, "").replaceAll(/(^|[^:])\/\/.*$/gm, "$1");
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the access token never reaches web storage", () => {
  it("test_no_module_outside_the_allowlist_touches_local_or_session_storage", () => {
    /**
     * The static half, in the shape of F0's `test_no_component_hardcodes_a
     * _colour`: crude, and it is what keeps the rule true after the twentieth
     * module. A grep cannot tell a token from a theme name, so the rule it
     * enforces is stricter and simpler — *this* file may write storage, and
     * nothing else may.
     *
     * The runtime test below is the one that proves the token specifically is
     * not there. Together they cover both the module that stores it deliberately
     * and the one that would do it by accident.
     */
    const offenders = sourceFiles(SRC)
      .filter((path) => /\b(local|session)Storage\b/.test(code(readFileSync(path, "utf8"))))
      .map((path) => relative(SRC, path).replaceAll("\\", "/"))
      .filter((path) => !(path in STORAGE_IS_ALLOWED) && !GENERATED.has(path));

    expect(offenders).toEqual([]);
  });

  it("test_a_full_sign_in_leaves_no_credential_in_local_or_session_storage", async () => {
    /**
     * The runtime half, and the one that would catch a token written through a
     * helper the grep above cannot see.
     *
     * `localStorage` is readable by any script the page ends up running, which
     * is the whole of what a cross-site scripting bug buys an attacker. The
     * long-lived half of the credential never reaches JavaScript at all — the
     * API sets it `httpOnly` — and the short-lived half lives in a module
     * variable that dies with the tab.
     */
    stubRouter((call) =>
      call.path === "/api/v1/auth/token"
        ? jsonResponse(200, {
            access_token: TOKEN,
            token_type: "Bearer",
            expires_in: 900,
            org_slug: "mnemos",
          })
        : jsonResponse(200, {
            user_id: "018f-user",
            email: "admin@mnemos.local",
            display_name: "Ada Admin",
            org_id: "018f-org",
            org_slug: "mnemos",
            session_id: "018f-session",
            permissions: [],
            tags: [],
          }),
    );

    await refreshAccessToken();
    await fetchIdentity();

    // The token is genuinely held — otherwise this passes because nothing
    // signed in, which is the vacuous version of the same assertion.
    expect(getAccessToken()).toBe(TOKEN);

    for (const store of [window.localStorage, window.sessionStorage]) {
      const contents = Object.entries({ ...store })
        .map(([key, value]) => `${key}=${String(value)}`)
        .join("\n");
      expect(contents).not.toContain(TOKEN);
      // Nothing that *looks* like a JWT either, however it was named.
      expect(contents).not.toMatch(/eyJ[A-Za-z0-9_-]{8,}/);
    }
  });

  it("test_no_module_writes_the_credential_to_a_cookie_from_javascript", () => {
    // The other place a token would be readable by script. The refresh cookie is
    // set by the API with `HttpOnly`; a client that wrote its own would remove
    // that flag by definition, because JavaScript cannot set it.
    const offenders = sourceFiles(SRC)
      .filter((path) => /document\.cookie/.test(code(readFileSync(path, "utf8"))))
      .map((path) => relative(SRC, path).replaceAll("\\", "/"))
      .filter((path) => !GENERATED.has(path));

    expect(offenders).toEqual([]);
  });
});

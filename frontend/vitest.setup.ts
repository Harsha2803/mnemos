import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

import compiledCss from "./src/app/globals.css?inline";
import {
  dropRulesJsdomCannotParse,
  flattenCascadeLayers,
  installMatchMedia,
  resetMediaQueries,
} from "./src/test/harness";
import { navigation, resetNavigation } from "./src/test/navigation";
import { resetRefreshForTests } from "./src/lib/auth/refresh";
import { resetSessionForTests } from "./src/lib/auth/session";

// `usePathname` returns `null` outside a router context and is harmless;
// `useRouter` throws. From A0 the app navigates — an unauthenticated visit is
// redirected to sign-in — so a router has to exist for every render. One double,
// installed once, and its calls readable in `src/test/navigation.ts`.
vi.mock("next/navigation", () => ({
  useRouter: () => navigation,
  usePathname: () => navigation.pathname,
  useSearchParams: () => navigation.searchParams,
  useParams: () => navigation.params,
}));

// The stylesheet the app actually ships, compiled by the same PostCSS/Tailwind
// pipeline, injected once into jsdom. Tests can then ask the document what a
// component resolves to instead of asserting on the class names it was handed.
const style = document.createElement("style");
style.setAttribute("data-mnemos", "globals");
style.textContent = dropRulesJsdomCannotParse(flattenCascadeLayers(compiledCss));
document.head.appendChild(style);

installMatchMedia();

/**
 * The suite is offline, and it is made offline here rather than trusted to be.
 *
 * A test that stubs `fetch` and unstubs it in `afterEach` can still leave an
 * async chain running — the session bootstrap is exactly that shape — and the
 * next thing that chain does is reach the real network. On a developer's
 * machine that request lands on the API container they happen to have running
 * and nothing looks wrong; on a CI runner it is `ECONNREFUSED ::1:8000`, and it
 * failed the job *after* all 74 tests had passed. CI found this, which is the
 * argument for CI.
 *
 * Assigned directly rather than through `vi.stubGlobal`, and before any test
 * runs, so that `vi.unstubAllGlobals()` restores *this* rather than the real
 * `fetch`. It answers 401 rather than throwing: a stray request is an
 * unauthenticated one, which every caller already handles, where a rejection
 * would surface as an unhandled promise in whichever chain outlived its test.
 */
globalThis.fetch = (async () =>
  new Response(
    JSON.stringify({ error: { code: "unauthenticated", message: "authentication failed" } }),
    { status: 401, headers: { "content-type": "application/json" } },
  )) as typeof globalThis.fetch;

beforeEach(() => {
  resetMediaQueries();
  resetNavigation();
  // The access token lives in a module variable (`session.ts`), which is the
  // whole point — and which means it survives `cleanup()` and would otherwise
  // leak one test's signed-in state into the next.
  resetSessionForTests();
  resetRefreshForTests();
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
});

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
}));

// The stylesheet the app actually ships, compiled by the same PostCSS/Tailwind
// pipeline, injected once into jsdom. Tests can then ask the document what a
// component resolves to instead of asserting on the class names it was handed.
const style = document.createElement("style");
style.setAttribute("data-mnemos", "globals");
style.textContent = dropRulesJsdomCannotParse(flattenCascadeLayers(compiledCss));
document.head.appendChild(style);

installMatchMedia();

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

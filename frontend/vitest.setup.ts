import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";

import compiledCss from "./src/app/globals.css?inline";
import {
  flattenCascadeLayers,
  installMatchMedia,
  resetMediaQueries,
} from "./src/test/harness";

// The stylesheet the app actually ships, compiled by the same PostCSS/Tailwind
// pipeline, injected once into jsdom. Tests can then ask the document what a
// component resolves to instead of asserting on the class names it was handed.
const style = document.createElement("style");
style.setAttribute("data-mnemos", "globals");
style.textContent = flattenCascadeLayers(compiledCss);
document.head.appendChild(style);

installMatchMedia();

beforeEach(() => {
  resetMediaQueries();
  document.documentElement.removeAttribute("data-theme");
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
});

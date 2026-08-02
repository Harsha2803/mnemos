import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import compiledCss from "@/app/globals.css?inline";
import { THEME_INIT_SCRIPT, THEME_STORAGE_KEY, resetPreferenceCache } from "@/lib/theme";

import { ThemeToggle } from "./ThemeToggle";

const frontendRoot = resolve(process.cwd());

/** What `globals.css` actually resolves a token to, given the current <html>. */
function token(name: string): string {
  return window.getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

beforeEach(() => {
  resetPreferenceCache();
});

describe("theming", () => {
  it("test_theme_toggle_overrides_the_system_preference_in_both_directions", async () => {
    // The failure mode this pins is one-directional and easy to ship: honouring
    // "I want dark" on a light OS while quietly ignoring "I want light" on a
    // dark one. Both directions are asserted, and so is the return to "system",
    // which is a third state rather than the absence of the other two.
    const user = userEvent.setup();
    render(<ThemeToggle />);

    // --- an explicit light choice, which must beat a dark OS ---------------
    await user.click(screen.getByRole("radio", { name: "Light" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "light");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(token("--bg")).toBe("#FFFFFF");
    expect(token("--label")).toBe("rgb(17 17 26 / 1.00)");

    // The half jsdom cannot evaluate — it has no real `prefers-color-scheme` —
    // is the media block's scope, and that scope is the entire mechanism. A
    // media block written `:root` instead of `:root:not([data-theme="light"])`
    // would still pass every assertion above and still show a dark-OS user the
    // dark theme they just declined.
    expect(compiledCss).toMatch(
      /@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root:not\(\[data-theme=["']?light["']?\]\)/,
    );

    // --- an explicit dark choice, which must beat a light OS ---------------
    await user.click(screen.getByRole("radio", { name: "Dark" }));

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(token("--bg")).toBe("#0B0B0F");
    expect(token("--label")).toBe("rgb(255 255 255 / 1.00)");

    // --- back to following the OS ------------------------------------------
    await user.click(screen.getByRole("radio", { name: "Match system" }));

    // Removed, not set to "system". `data-theme="system"` matches neither rule
    // and would pin every OS-following user to the light palette.
    expect(document.documentElement).not.toHaveAttribute("data-theme");
    expect(token("--bg")).toBe("#FFFFFF");
  });

  it("test_the_two_dark_palettes_declare_the_same_tokens", () => {
    // The dark palette is written twice — once under the media query, once
    // under [data-theme="dark"] — because CSS has no way to share one block
    // between a media query and a selector. Drift between them is a subtly
    // wrong shade in exactly one of the two modes, which is the kind of defect
    // nobody reports. So it is a test failure instead.
    const source = readFileSync(join(frontendRoot, "src/app/globals.css"), "utf8");

    const media = /@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{([\s\S]*?)\n {2}\}\n\}/.exec(
      source,
    );
    const explicit = /:root\[data-theme="dark"\] \{([\s\S]*?)\n\}/.exec(source);

    expect(media, "no prefers-color-scheme dark block").not.toBeNull();
    expect(explicit, "no [data-theme=dark] block").not.toBeNull();

    const declarations = (block: string): string[] =>
      block
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => line.startsWith("--"))
        .map((line) => line.replace(/\s+/g, " "));

    const fromMedia = declarations((media as RegExpExecArray)[1] as string);
    const fromExplicit = declarations((explicit as RegExpExecArray)[1] as string);

    expect(fromMedia.length).toBeGreaterThan(15);
    expect(fromExplicit).toEqual(fromMedia);
  });

  it("test_the_pre_paint_script_applies_a_stored_choice_before_react_exists", () => {
    // Runs the shipped script itself, not a re-implementation of it.
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");
    new Function(THEME_INIT_SCRIPT)();

    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(token("--bg")).toBe("#0B0B0F");
  });

  it("test_the_pre_paint_script_survives_storage_being_unavailable", () => {
    // localStorage throws outright in a partitioned or cookie-blocked context.
    // An exception in a head script aborts parsing of the rest of the head, so
    // "the theme did not persist" would become "the page did not load".
    const original = window.localStorage.getItem;
    window.localStorage.getItem = () => {
      throw new DOMException("blocked", "SecurityError");
    };

    try {
      expect(() => new Function(THEME_INIT_SCRIPT)()).not.toThrow();
      expect(document.documentElement).not.toHaveAttribute("data-theme");
    } finally {
      window.localStorage.getItem = original;
    }
  });

  it("test_the_theme_script_is_inlined_in_the_head_and_is_not_deferred", () => {
    // Structural, because there is no way to observe "before first paint" in
    // jsdom. What can be observed is the one property that makes it true: the
    // script is inline, in <head>, and carries neither `defer` nor `async` —
    // either of which moves it after the paint it exists to precede.
    const layout = readFileSync(join(frontendRoot, "src/app/layout.tsx"), "utf8");

    const head = /<head>([\s\S]*?)<\/head>/.exec(layout);
    expect(head, "root layout renders no <head>").not.toBeNull();

    // Strip the JSX comment: prose about what `defer` would break must not be
    // mistaken for a `defer` attribute.
    const contents = ((head as RegExpExecArray)[1] as string).replace(
      /\{\/\*[\s\S]*?\*\/\}/g,
      "",
    );
    expect(contents).toContain("THEME_INIT_SCRIPT");
    expect(contents).toMatch(/<script\b/);
    expect(contents).not.toMatch(/\bdefer\b|\basync\b|next\/script/);
    expect(layout).toContain("suppressHydrationWarning");
  });

  it("test_the_appearance_control_is_reachable_by_role_and_name", () => {
    // Querying by role and accessible name is an accessibility assertion as
    // much as a behavioural one: it fails if the icons ever lose their labels.
    render(<ThemeToggle />);

    expect(screen.getByRole("radiogroup", { name: "Appearance" })).toBeInTheDocument();
    for (const name of ["Match system", "Light", "Dark"]) {
      expect(screen.getByRole("radio", { name })).toBeInTheDocument();
    }
  });
});

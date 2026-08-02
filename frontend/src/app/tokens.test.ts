import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import compiledCss from "./globals.css?inline";

// Vitest runs with the cwd set to the Vite root, which is `frontend/`.
const frontendRoot = resolve(process.cwd());
const repoRoot = resolve(frontendRoot, "..");
const tokensSource = readFileSync(join(frontendRoot, "src/app/globals.css"), "utf8");

/**
 * Files that may legitimately name a colour: the tokens themselves, the
 * generated client, and the tests that assert on token values. Everything else
 * is a component and is subject to C13.
 */
function componentSources(): string[] {
  const found: string[] = [];

  function walk(dir: string): void {
    for (const entry of readdirSync(dir)) {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) {
        if (entry === "node_modules" || entry === "test") continue;
        walk(path);
        continue;
      }
      if (!/\.(ts|tsx|css)$/.test(entry)) continue;
      if (/\.test\.(ts|tsx)$/.test(entry)) continue;
      if (entry === "globals.css" || entry === "schema.ts") continue;
      found.push(path);
    }
  }

  walk(join(frontendRoot, "src"));
  return found;
}

/** Every `--name: value;` declaration inside the ```css blocks of a section. */
function declaredCustomProperties(css: string): Set<string> {
  const names = new Set<string>();
  for (const match of css.matchAll(/(--[\w-]+)\s*:/g)) {
    names.add(match[1] as string);
  }
  return names;
}

describe("design tokens", () => {
  it("test_no_component_hardcodes_a_colour", () => {
    // Crude on purpose, and it is the check that keeps C13 true after the
    // twentieth component. A hex in one button is not a bug on the day it is
    // written; it is a bug on the day the palette changes and one control does
    // not move with it.
    const hex = /#[0-9a-fA-F]{3,8}\b/;
    const colourFunction = /\b(?:rgba?|hsla?|oklch|lab|color-mix)\s*\(/;

    const offenders: string[] = [];
    for (const path of componentSources()) {
      const contents = readFileSync(path, "utf8");
      contents.split("\n").forEach((line, index) => {
        if (hex.test(line) || colourFunction.test(line)) {
          offenders.push(`${path.slice(frontendRoot.length)}:${index + 1}: ${line.trim()}`);
        }
      });
    }

    expect(offenders).toEqual([]);
  });

  it("test_there_is_no_tailwind_config_beside_the_tokens", () => {
    // C13: the tokens *are* the configuration. A `tailwind.config.*` is the
    // second source of truth that constraint exists to prevent, and Tailwind v4
    // would silently prefer it.
    const configs = readdirSync(frontendRoot).filter((name) =>
      /^tailwind\.config\.(js|cjs|mjs|ts)$/.test(name),
    );
    expect(configs).toEqual([]);
  });

  it("test_every_token_in_the_design_system_is_defined_in_globals_css", () => {
    // The design system is normative (C13). If §2 names a token that
    // `globals.css` does not define, a component will reach for a literal
    // instead — so the gap is closed here rather than discovered later.
    const designSystem = readFileSync(join(repoRoot, "docs/DesignSystem.md"), "utf8");
    const section = designSystem.slice(
      designSystem.indexOf("\n## 2. Tokens"),
      designSystem.indexOf("\n## 3. Accessibility"),
    );
    expect(section.length).toBeGreaterThan(1000);

    const documented = declaredCustomProperties(section);
    const defined = declaredCustomProperties(tokensSource);

    const missing = [...documented].filter((name) => !defined.has(name)).sort();
    expect(missing).toEqual([]);
  });

  it("test_the_tailwind_palette_is_only_the_design_tokens", () => {
    // `--color-*: initial` in the @theme block deletes Tailwind's built-in
    // palette. Without it `bg-red-500` stays spellable, contains no hex literal,
    // and sails straight past the grep above.
    expect(compiledCss).not.toMatch(/--color-(?:red|blue|green|slate|gray|zinc)-\d00/);
    expect(compiledCss).toContain("--color-accent:");
    expect(compiledCss).toContain("--color-label-secondary:");
  });

  it("test_the_spacing_scale_and_the_tailwind_scale_are_the_same_numbers", () => {
    // `--spacing: 0.25rem` is what makes `p-4` resolve to exactly --space-4.
    // If the two ever disagree, half the app is on an 8pt rhythm and half is
    // not, which is the failure mode §2.3 describes as invisible.
    expect(tokensSource).toMatch(/--spacing:\s*0\.25rem/);
    expect(tokensSource).toMatch(/--space-4:\s*1rem/);
    expect(tokensSource).toMatch(/--space-16:\s*4rem/);
  });

  it("test_reduced_motion_collapses_every_transition_and_animation", () => {
    // DesignSystem §2.5: for some users motion is a vestibular trigger, so this
    // is mandatory rather than a nicety. Asserted against the *compiled* sheet,
    // because a rule that PostCSS dropped is a rule that does not ship.
    const block = /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\n\}/.exec(
      compiledCss,
    );
    expect(block, "no prefers-reduced-motion block in the compiled stylesheet").not.toBeNull();

    const body = (block as RegExpExecArray)[1] as string;
    expect(body).toMatch(/\*\s*,\s*\*::before\s*,\s*\*::after/);
    expect(body).toMatch(/animation-duration:\s*0\.01ms\s*!important/);
    expect(body).toMatch(/animation-iteration-count:\s*1\s*!important/);
    expect(body).toMatch(/transition-duration:\s*0\.01ms\s*!important/);
    expect(body).toMatch(/scroll-behavior:\s*auto\s*!important/);
  });

  it("test_the_chrome_material_has_an_opaque_fallback", () => {
    // Translucent chrome over unblurred content is illegible, so the fallback
    // is part of the material and not an enhancement (DesignSystem §2.4).
    expect(compiledCss).toContain("backdrop-filter: var(--material-regular)");
    expect(compiledCss).toMatch(
      /@supports not \(backdrop-filter: blur\(1px\)\)\s*\{[\s\S]*?\.material-chrome\s*\{[\s\S]*?background-color:\s*var\(--bg-secondary\)/,
    );
  });
});

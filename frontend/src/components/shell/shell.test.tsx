import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

// The App Router double lives in `vitest.setup.ts` from A0, because the shell
// now contains components that *navigate* — `useRouter` throws outside a router,
// where `usePathname` merely returned `null`. A file-local `vi.mock` here would
// replace the global one wholesale rather than extend it, and the shell would
// lose the router it needs.

import compiledCss from "@/app/globals.css?inline";
import { resolvedPx, setMediaQueries } from "@/test/harness";
import { renderWithProviders, stubJsonResponse } from "@/test/render";

import { AppShell } from "./AppShell";
import { INSPECTOR_INLINE, SIDEBAR_INLINE } from "./useMediaQuery";

const INTERACTIVE = 'button, a[href], input, select, textarea, [role="button"]';

function viewport(width: number): void {
  setMediaQueries({
    [INSPECTOR_INLINE]: width >= 1024,
    [SIDEBAR_INLINE]: width >= 768,
  });
}

function renderShell() {
  return renderWithProviders(
    <AppShell>
      <h1>Overview</h1>
    </AppShell>,
  );
}

beforeEach(() => {
  // The sidebar footer calls /readyz for real. A healthy answer keeps these
  // tests about layout rather than about what a failed probe looks like — that
  // is `health.test.tsx`'s job.
  stubJsonResponse(200, { status: "ready", checks: { postgres: "ok", redis: "ok" } });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the three-column shell", () => {
  it("test_the_desktop_shell_has_all_three_columns", () => {
    viewport(1440);
    renderShell();

    // Landmarks, not divs. Each is reachable by role and name, which is how a
    // screen-reader user skips between the three regions at all.
    expect(screen.getByRole("navigation", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.getByRole("main")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Context inspector" })).toBeInTheDocument();

    // The inspector renders an EmptyState until M4 fills it, not fake rows.
    expect(
      screen.getByRole("heading", { level: 3, name: "No message selected" }),
    ).toBeInTheDocument();
  });

  it("test_the_inspector_collapses_and_reopens_on_the_desktop", async () => {
    viewport(1440);
    renderShell();

    const toggle = screen.getByRole("button", { name: "Hide context inspector" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", "context-inspector");

    await userEvent.click(toggle);

    // Collapsed, not removed: it keeps its place in the layout and in the
    // user's mental model (DesignSystem §1).
    const collapsed = screen.getByRole("complementary", { name: "Context inspector" });
    expect(collapsed).toHaveClass("w-0");
    expect(screen.queryByRole("heading", { name: "No message selected" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Show context inspector" }));
    expect(screen.getByRole("heading", { name: "No message selected" })).toBeInTheDocument();
  });

  it("test_below_1024px_the_inspector_becomes_an_overlay_sheet", async () => {
    viewport(900);
    renderShell();

    // The sidebar is still a column at 900px — only the inspector has moved.
    expect(screen.getByRole("navigation", { name: "Workspace" })).toBeInTheDocument();
    expect(screen.queryByRole("complementary", { name: "Context inspector" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Show context inspector" }));

    // A dialog, not a narrower column: focus is trapped and Esc closes it,
    // which is the behaviour a column cannot provide.
    const sheet = screen.getByRole("dialog", { name: "Context inspector" });
    expect(sheet).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "No message selected" }),
    ).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("test_below_768px_the_sidebar_becomes_an_overlay_sheet_too", async () => {
    viewport(600);
    renderShell();

    expect(screen.queryByRole("navigation", { name: "Workspace" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Open navigation" }));

    const sheet = screen.getByRole("dialog", { name: "Workspace" });
    expect(sheet).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Sections" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "aria-current",
      "page",
    );

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("test_the_shell_has_no_axe_violations", async () => {
    viewport(1440);
    const { container } = renderShell();

    const results = await axe(container);
    expect(results.violations).toEqual([]);
  });

  it("test_every_interactive_target_is_at_least_44px", async () => {
    viewport(1440);
    renderShell();

    const targets = Array.from(document.body.querySelectorAll(INTERACTIVE));
    expect(targets.length).toBeGreaterThanOrEqual(5);

    for (const target of targets) {
      const label = target.getAttribute("aria-label") ?? target.textContent ?? "(unnamed)";
      const minHeight = resolvedPx(target, "min-height");
      const minWidth = resolvedPx(target, "min-width");

      expect(minHeight, `${label}: no resolvable min-height`).not.toBeNull();
      expect(minWidth, `${label}: no resolvable min-width`).not.toBeNull();
      expect(minHeight as number, `${label}: min-height`).toBeGreaterThanOrEqual(44);
      expect(minWidth as number, `${label}: min-width`).toBeGreaterThanOrEqual(44);
    }
  });

  it("test_the_chrome_is_translucent_with_an_opaque_fallback", () => {
    viewport(1440);
    renderShell();

    // Both pieces of chrome opt into the material, and the material carries its
    // fallback — translucent chrome over unblurred content is illegible, so a
    // browser without backdrop-filter must get an opaque bar, not a see-through
    // one (DesignSystem §2.4).
    expect(screen.getByRole("navigation", { name: "Workspace" })).toHaveClass("material-chrome");
    expect(screen.getByRole("banner")).toHaveClass("material-chrome");
    expect(compiledCss).toMatch(
      /@supports not \(backdrop-filter: blur\(1px\)\)[\s\S]{0,200}background-color:\s*var\(--bg-secondary\)/,
    );
  });

  it("test_the_content_column_is_capped_at_the_readable_measure", () => {
    viewport(1440);
    renderShell();

    const heading = screen.getByRole("heading", { name: "Overview" });
    const measured = heading.closest(".measure");
    expect(measured, "content is not inside a .measure container").not.toBeNull();

    // 46rem at the 16px root the tokens assume. Line length is a legibility
    // control, not a layout preference (DesignSystem §2.2).
    expect(window.getComputedStyle(measured as Element).maxWidth).toBe("var(--measure)");
    expect(compiledCss).toMatch(/--measure:\s*46rem/);
  });
});

"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * The two breakpoints the shell changes shape at (DesignSystem §1, F0.4).
 * Named, because `1024` appearing in three files is three numbers.
 */
export const INSPECTOR_INLINE = "(min-width: 1024px)";
export const SIDEBAR_INLINE = "(min-width: 768px)";

/**
 * Whether a media query currently matches, kept live.
 *
 * The shell needs this in JavaScript, not only in CSS, because below the
 * breakpoint the inspector is not a narrower column — it is a *different
 * component*, a modal sheet with focus trapping and an Esc handler. CSS can
 * hide a panel; it cannot turn one into a dialog.
 *
 * `serverFallback` is what SSR renders. This is a desktop workspace, so both
 * call sites pass `true` and the first paint is the three-column layout; a
 * narrow viewport corrects itself on hydration, which is the right way round —
 * the alternative flashes a mobile shell at every desktop user.
 */
export function useMediaQuery(query: string, serverFallback: boolean): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );

  const getSnapshot = useCallback(() => window.matchMedia(query).matches, [query]);

  return useSyncExternalStore(subscribe, getSnapshot, () => serverFallback);
}

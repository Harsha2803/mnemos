"use client";

import { useSyncExternalStore } from "react";

import {
  getPreference,
  getServerPreference,
  subscribeToPreference,
  type ThemePreference,
} from "@/lib/theme";

/**
 * The current preference, kept in step with other tabs.
 *
 * `useSyncExternalStore` rather than `useState` + `useEffect` because the value
 * genuinely lives outside React — in `localStorage`, written by a script that
 * ran before React existed on the page. React handles the server/client
 * disagreement itself, so there is no hydration warning and no first frame in
 * which the toggle disagrees with the theme already on screen.
 */
export function useThemePreference(): ThemePreference {
  return useSyncExternalStore(subscribeToPreference, getPreference, getServerPreference);
}

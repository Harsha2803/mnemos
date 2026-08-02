/**
 * Theme preference: a tiny store over `localStorage` plus the script that reads
 * it before first paint.
 *
 * Three values, not two. "system" is a real preference — it means *keep
 * following the OS* — and collapsing it into a light/dark boolean loses the
 * user's answer the moment they change their OS setting. The CSS in
 * `globals.css` is written so that the absence of `data-theme` means "system",
 * which is why this module removes the attribute rather than computing a value.
 *
 * Nothing here touches React, so `layout.tsx` — a server component — can import
 * the init script without pulling a client boundary along with it.
 */

export type ThemePreference = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "mnemos.theme";

export function isThemePreference(value: unknown): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

/**
 * The blocking script that runs in `<head>` before the body is parsed.
 *
 * It has to be a string, and it has to be inline: a deferred or external script
 * runs after the first paint, and the user sees a white flash before the dark
 * theme arrives. It reads `localStorage` synchronously, which is exactly the
 * kind of thing to avoid everywhere except here.
 *
 * `try/catch` is not defensive padding — `localStorage` throws outright in a
 * partitioned or cookie-blocked context, and an exception here would abort
 * parsing of the rest of the head.
 */
export const THEME_INIT_SCRIPT = `(function(){try{var p=localStorage.getItem(${JSON.stringify(
  THEME_STORAGE_KEY,
)});if(p==="light"||p==="dark"){document.documentElement.setAttribute("data-theme",p);}}catch(e){}})();`;

/**
 * Stamp the choice on `<html>`. "system" *removes* the attribute so the
 * `prefers-color-scheme` block in `globals.css` governs again — setting
 * `data-theme="system"` instead would match neither rule and pin the app to
 * light for everyone who chose to follow their OS.
 */
export function applyPreference(preference: ThemePreference): void {
  const root = document.documentElement;
  if (preference === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", preference);
}

export function readStoredPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePreference(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

// ------------------------------------------------------------------- store

const listeners = new Set<() => void>();
let cached: ThemePreference | null = null;

function notify(): void {
  for (const listener of listeners) listener();
}

function onStorage(event: StorageEvent): void {
  if (event.key !== null && event.key !== THEME_STORAGE_KEY) return;
  cached = readStoredPreference();
  applyPreference(cached);
  notify();
}

/** Subscribe to preference changes, including ones made in another tab. */
export function subscribeToPreference(listener: () => void): () => void {
  if (listeners.size === 0) window.addEventListener("storage", onStorage);
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) window.removeEventListener("storage", onStorage);
  };
}

export function getPreference(): ThemePreference {
  if (cached === null) cached = readStoredPreference();
  return cached;
}

/**
 * The server has no `localStorage` and must not guess, so it renders the
 * neutral answer. `useSyncExternalStore` swaps in the real one after hydration
 * without a mismatch warning — which is the whole reason the toggle is wired to
 * a store rather than to `useState` + `useEffect`.
 */
export function getServerPreference(): ThemePreference {
  return "system";
}

export function setPreference(preference: ThemePreference): void {
  cached = preference;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // A blocked storage context still gets the theme it asked for; it just
    // does not get it back on the next visit. Failing the click would be worse.
  }
  applyPreference(preference);
  notify();
}

/** Test seam: drop the memoised value so a fresh render re-reads storage. */
export function resetPreferenceCache(): void {
  cached = null;
}

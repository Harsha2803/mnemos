/**
 * Test harness for the two things jsdom does not do on its own.
 *
 * Neither of these is a convenience. Without the first, every assertion about a
 * rendered component's size or colour would be an assertion about its class
 * attribute — which is a restatement of the component's source, not evidence.
 * Without the second, anything that reads a media query throws.
 */

/**
 * jsdom's CSS parser predates cascade layers and silently drops every rule
 * inside an `@layer` block. That is most of the stylesheet: Tailwind emits
 * preflight, the generated utilities and our own component classes into layers,
 * so an unflattened sheet gives jsdom eleven rules out of several hundred.
 *
 * Removing the layer *wrappers* — the `@layer name { … }` braces, not the rules
 * inside them — leaves jsdom a flat sheet it can parse. Layer ordering is lost,
 * which does not matter here: jsdom is not resolving cross-layer conflicts, and
 * a test that depended on layer precedence would be testing the browser rather
 * than the app.
 */
export function flattenCascadeLayers(css: string): string {
  // `@layer base, components, utilities;` — a declaration, no block.
  let out = css.replace(/@layer[^;{]*;/g, "");

  for (;;) {
    const match = /@layer[^{]*\{/.exec(out);
    if (match === null) break;

    const openIndex = match.index + match[0].length - 1;
    const closeIndex = matchingBrace(out, openIndex);
    if (closeIndex === -1) break;

    out =
      out.slice(0, match.index) +
      out.slice(openIndex + 1, closeIndex) +
      out.slice(closeIndex + 1);
  }

  return out;
}

/**
 * jsdom's selector parser rejects CSS identifier escapes, so every Tailwind
 * variant that puts a bracket in the class name — `data-[state=on]:bg-bg`,
 * `size-[18px]` — makes it fail the *whole* stylesheet parse and log
 * "Could not parse CSS stylesheet". The rules were being discarded either way;
 * dropping them here keeps the parse clean and the failure honest, because a
 * test that silently lost half the sheet is worse than one that never had it.
 *
 * Nothing asserted in this suite depends on a bracketed variant. If something
 * ever does, it needs a browser — Playwright, from M3.4 — not a looser jsdom.
 */
export function dropRulesJsdomCannotParse(css: string): string {
  const kept: string[] = [];
  let depth = 0;
  let start = 0;

  for (let i = 0; i < css.length; i += 1) {
    const ch = css[i];
    if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) {
        const chunk = css.slice(start, i + 1);
        start = i + 1;
        const selector = chunk.slice(0, chunk.indexOf("{"));
        if (!selector.includes("\\")) kept.push(chunk);
      }
    }
  }

  return kept.join("\n");
}

function matchingBrace(text: string, openIndex: number): number {
  let depth = 0;
  for (let i = openIndex; i < text.length; i += 1) {
    const ch = text[i];
    if (ch === "{") depth += 1;
    else if (ch === "}") {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/**
 * Resolve a computed length that jsdom hands back unresolved.
 *
 * jsdom implements the cascade but not `var()` substitution, so a declaration
 * written `min-height: var(--hit-target)` computes to the literal string
 * `"var(--hit-target)"`. Custom properties themselves *are* resolved, so one
 * lookup on the root closes the gap. Returns `null` when the property is not
 * set at all, which a caller should treat as a failure rather than as zero.
 */
export function resolvedPx(element: Element, property: string): number | null {
  const declared = window.getComputedStyle(element).getPropertyValue(property).trim();
  if (declared === "") return null;

  const variable = /^var\(\s*(--[\w-]+)\s*\)$/.exec(declared);
  const literal =
    variable === null
      ? declared
      : window
          .getComputedStyle(document.documentElement)
          .getPropertyValue(variable[1] as string)
          .trim();

  const px = /^(-?[\d.]+)px$/.exec(literal);
  return px === null ? null : Number(px[1]);
}

// --------------------------------------------------------------- matchMedia

type Listener = (event: MediaQueryListEvent) => void;

const listeners = new Map<string, Set<Listener>>();
let matches: Record<string, boolean> = {};

/**
 * jsdom ships no `window.matchMedia` at all, so anything that asks about the
 * viewport or the colour scheme throws on the first render. This stub answers
 * from a table the test controls and, unlike the usual one-liner mock, it
 * notifies listeners — which is the half that lets a test drive the shell
 * across a breakpoint instead of only rendering it on one side of one.
 */
export function installMatchMedia(): void {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (query: string): MediaQueryList => {
      const list: MediaQueryList = {
        media: query,
        get matches() {
          return matches[query] ?? false;
        },
        onchange: null,
        addEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
          const set = listeners.get(query) ?? new Set<Listener>();
          set.add(listener as Listener);
          listeners.set(query, set);
        },
        removeEventListener: (_type: string, listener: EventListenerOrEventListenerObject) => {
          listeners.get(query)?.delete(listener as Listener);
        },
        addListener: () => undefined,
        removeListener: () => undefined,
        dispatchEvent: () => false,
      };
      return list;
    },
  });
}

/** Set which media queries match, and tell every subscriber they changed. */
export function setMediaQueries(next: Record<string, boolean>): void {
  matches = { ...matches, ...next };
  for (const [query, set] of listeners) {
    const event = { matches: matches[query] ?? false, media: query } as MediaQueryListEvent;
    for (const listener of set) listener(event);
  }
}

/** Forget every query and subscriber. Called between tests. */
export function resetMediaQueries(): void {
  matches = {};
  listeners.clear();
}

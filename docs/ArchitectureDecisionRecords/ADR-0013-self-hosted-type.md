# ADR-0013 — Self-hosted type: a serif to read, a sans to operate, a mono to identify

**Status:** Accepted · **Date:** 2026-10-22 · **Supersedes:** DesignSystem §0's "system font
stack, no webfonts" row (2026-07, `F0`)

## Context

DesignSystem §0 chose the system font stack (`-apple-system, BlinkMacSystemFont, "Inter",
…, Arial`) on the reasoning that it renders as SF on Apple devices at zero download cost.
That reasoning holds only for Apple devices. Inter was listed but never shipped, so on
Linux and Windows, which is where most interviewers will open the demo, the stack falls
through to **Arial or Liberation Sans**. The screenshots taken on 2026-10-22
(`docs/screens/`, before the revamp) show exactly that.

Type is also the largest single lever on whether an interface reads as a product with its
own character or as a default template. The owner's feedback was that Mnemos reads as a
generic AI-generated app. Every answer, document passage and identifier in Mnemos is set
in whatever face the visitor's OS happens to have, so the product has no typographic voice.

Mnemos's content has three kinds of text, and they want different faces:

- **What is read:** answers, quoted passages, document excerpts. Long-form, at a measure.
- **What is operated:** navigation, labels, buttons, forms.
- **What is identified:** document IDs, digests, SQL, job IDs, page and character ranges.

## Decision

Self-host three SIL OFL 1.1 families through `next/font/local`, committed under
`frontend/src/app/fonts/` with their licences:

| Role | Family | File | Bytes |
|---|---|---|---|
| reading | Source Serif 4, variable weight | `source-serif-4-latin-wght.woff2` | 50,936 |
| interface | IBM Plex Sans, variable weight | `ibm-plex-sans-latin-wght.woff2` | 45,712 |
| identifiers | IBM Plex Mono, 400 | `ibm-plex-mono-latin-400.woff2` | 14,708 |

**Budget: 111,356 bytes (≈109 KB) for all three, latin subset only, `font-display: swap`.**
No italic files, no second mono weight, no other subsets. Browsers synthesize italic for
the rare emphasis; answers are plain text today. Adding a style, weight or subset changes
this budget and needs this ADR updated with the new measured total.

## Rationale

**Consistency across platforms beats native rendering on one.** The system stack gave
Apple visitors SF and everyone else Arial, which means two different products. One
committed set of files gives every visitor the same metrics, the same measure and the same
hierarchy, and that is what the design system's tokens assume.

**Self-hosted, not a font CDN.** `next/font/local` turns the files into hashed static
assets served by the app itself. Nothing is requested from a third party at runtime
(privacy, no extra connection, works offline on a laptop demo), and nothing is fetched at
build time either. `next/font/google` would download at build, which makes the Docker
build depend on Google's font API. C1 (zero cost) holds: OFL fonts are free to bundle and
redistribute.

**Why these families.** Source Serif 4 is a screen serif with a generous x-height that
holds at 17px body text. Newsreader was compared on the same specimen: it has more
character but reads smaller at the same size, and it is 7 KB heavier. IBM Plex Sans and
Plex Mono share skeletons, so a digest set in mono inside a sans sentence does not jolt,
and Plex's engineered, slightly mechanical texture is a deliberate contrast to the serif.
None of the three is the default face of any AI chat product the owner was compared to.

**Swap, with metric-matched fallbacks.** `next/font` generates a size-adjusted fallback
face for each family, so the swap from fallback to webfont does not reflow lines. Text is
readable from the first paint.

## Consequences

- ~109 KB of fonts on a cold load, cached immutably afterwards. That is larger than the
  previous zero, and small next to the JavaScript bundle.
- The `--font-sans`, `--font-serif` and `--font-mono` tokens lead with the `next/font`
  variables, which live on `<html>`. A component asks for `font-serif`, never for a family
  name.
- Apple's assets stay out (DesignSystem §0): no SF Pro, no SF Symbols.
- If a future screen needs Greek, Cyrillic or Vietnamese, add that subset deliberately
  and re-measure. Do not switch to the full files.

# Design System

> **Read this before writing any component.** It is the frontend counterpart to
> [`CodingStandards.md`](CodingStandards.md): rules, with the reason attached, because a
> rule whose rationale is unknown gets worked around the first time it is inconvenient.

This is **Mnemos's own design system**. Its reference point is Apple's
[Design Resources](https://developer.apple.com/design/resources/) and
[Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines) —
studied as a source of ideas about typography, spatial rhythm, materials and interaction
character, and adapted here for a desktop web app.

**It is not an Apple product, does not imitate one, and claims no association.** Where the
sections below cite Apple, they cite a *technique* — a type scale, an opacity model for
text hierarchy, a three-column layout — not a look to be reproduced. Mnemos should feel
considered and native-quality on a Mac; it should not be mistaken for an Apple app.

---

## 0. What we adopt, and what we do not

**Adopted, because each solves a problem this app actually has:**

| Idea | What we take | Why it earns its place here |
|---|---|---|
| **Typography** | The system font stack, and a type scale with tight tracking at large sizes | Mnemos displays provenance — which revision, which tag, which claim superseded which. That is detail that must be *readable*, and a real hierarchy is what makes it scannable |
| **Spatial rhythm** | An 8pt grid with 4pt half-steps | Consistent rhythm is what makes an interface feel composed rather than assembled. Invisible until one component opts out |
| **Semantic colour** | Roles (`--label-secondary`) rather than literals (`--gray-600`), expressed as opacity over the background | Opacity-based labels stay correct on *any* surface, including translucent ones — which a literal grey does not |
| **Materials** | Translucency + saturation for chrome, with an opaque fallback | Lets the sidebar and toolbar recede so the conversation is the loudest thing on screen |
| **Depth over decoration** | Layers and hairlines carry hierarchy; shadows are a last resort | The context bundle sits *behind* the answer. A panel that slides over says that without a sentence of explanation |
| **Motion character** | Purposeful, quick, spring-like; reduced-motion honoured absolutely | Motion should say where a thing came from, not perform personality |
| **Accessibility floors** | 44px targets, visible focus, contrast minimums, never colour alone | Cheap while a component is being written, expensive across forty of them |
| **Three-column layout** | Sidebar / content / inspector | §1 — it happens to be this product's information architecture exactly |

**Not adopted — two of these are practical constraints on assets, not stylistic choices:**

| Not used | Why | Instead |
|---|---|---|
| **SF Pro as a webfont** | Apple's font licence covers apps on Apple platforms, not general web distribution | The **system font stack** (`-apple-system`, `BlinkMacSystemFont`). It renders as SF on Apple devices because the OS already has it, and degrades cleanly elsewhere. **Inter** (SIL OFL) as the explicit fallback — this is the right answer anyway, since a system font needs no download at all |
| **SF Symbols** | Same asset-licence boundary | **Lucide** (ISC). Consistent 1.5px stroke, geometrically similar, tree-shakeable React components |
| **Apple's visual identity** | We are building our own product, not a lookalike | Our own accent, our own iconography, our own voice. The *system* is borrowed; the *identity* is ours |

---

## 1. The three ideas the system is built on

Apple's HIG organises itself around **clarity, deference and depth**. Those three happen
to describe what this product needs, which is why they are the frame here rather than
some other vocabulary.

**Deference — the UI defers to the content.** The content is a conversation and the
documents behind it. Chrome should be quiet: hairline separators, translucent toolbars, no
box drawn around something whitespace has already grouped. Every pixel of decoration
competes with a citation.

**Clarity — legibility over density.** See the typography row above. Generous line height,
a real hierarchy, and colour used to signal state rather than to decorate.

**Depth — layers communicate hierarchy.** The context bundle is *behind* the answer, and an
inspector that slides in from the right, on a material background, communicates that
relationship structurally.

### The layout follows from this

The sidebar / content / inspector arrangement is not a stylistic borrowing — it is this
product's information architecture:

```
┌────────────┬──────────────────────────────┬──────────────┐
│  Sidebar   │  Content                     │  Inspector   │
│            │                              │              │
│ conversa-  │  the conversation            │  the context │
│ tions,     │  messages, citations,        │  bundle for  │
│ folders,   │  the composer                │  the selected│
│ knowledge, │                              │  message     │
│ sources    │                              │              │
│            │                              │  (collapsible│
│ 260px      │  fluid, max 46rem readable   │   320px)     │
└────────────┴──────────────────────────────┴──────────────┘
```

The inspector is the feature. It gets a permanent home on the right — the conventional
place for one on the desktop — and it collapses rather than disappearing from the mental
model.

---

## 2. Tokens

Everything below is a CSS custom property, and these values are **ours** — derived from
studying the reference material, then tuned for a desktop web app. **No component
hard-codes a colour, a radius, or a spacing value.** A magic number in a component is a value that cannot be themed and
will drift from its neighbours.

### 2.1 Colour — semantic, never literal

Semantic roles, not a palette. `--label-secondary` survives a redesign; `--gray-600` does
not, because the next redesign changes which grey it should be.

```css
:root {
  /* Accent — Mnemos indigo. One accent, for interactive affordances only, never for
     decoration. 7.18:1 against white, so it is legible as link text and takes white
     text when used as a fill. */
  --accent:              #4A3FD1;
  --accent-hover:        #3E34B8;
  --on-accent:           #FFFFFF;

  /* Label hierarchy as opacity over the background, which is why these stay correct on
     any surface — including a translucent one. */
  --label:               rgb(17 17 26 / 1.00);
  --label-secondary:     rgb(17 17 26 / 0.62);
  --label-tertiary:      rgb(17 17 26 / 0.32);
  --label-quaternary:    rgb(17 17 26 / 0.18);

  /* Backgrounds, in stacking order. Faintly cool neutrals — a pure grey reads clinical
     next to long-form text. */
  --bg:                  #FFFFFF;
  --bg-secondary:        #F4F5F7;
  --bg-tertiary:         #FFFFFF;
  --bg-grouped:          #F4F5F7;

  /* Fills — for controls and non-text surfaces that sit *on* a background. */
  --fill:                rgb(17 17 26 / 0.08);
  --fill-secondary:      rgb(17 17 26 / 0.06);
  --fill-tertiary:       rgb(17 17 26 / 0.04);

  /* Hairlines. Translucent, so a separator works over any material. */
  --separator:           rgb(17 17 26 / 0.12);
  --separator-opaque:    #E2E3E8;

  /* State. Each has exactly one meaning in this app, and each is dark enough to be used
     as text on --bg (measured, see below). */
  --success:             #15703C;   /* a claim is current / a job succeeded */
  --warning:             #9A5B00;   /* superseded, degraded, stale */
  --danger:              #C2352E;   /* denied, failed, revoked */
  --info:                #5B4BE1;   /* system / compiler annotation */

  /* Accent at 12% — the `tinted` button rank (§4), as a token rather than a
     colour-mix at each call site, so the one number that defines the rank lives
     in one place. The hover partner deepens the tint instead of shifting hue,
     so the rank stays recognisable while pressed. */
  --accent-tint:         rgb(74 63 209 / 0.12);
  --accent-tint-hover:   rgb(74 63 209 / 0.20);

  /* The chrome material's own translucency. Always paired with --material-*
     and the opaque @supports fallback in §2.4. */
  --chrome:              rgb(255 255 255 / 0.72);
}

@media (prefers-color-scheme: dark) {
  :root {
    --accent:            #9B8CFF;
    --accent-hover:      #B0A4FF;
    --on-accent:         #14121F;

    --label:             rgb(255 255 255 / 1.00);
    --label-secondary:   rgb(255 255 255 / 0.62);
    --label-tertiary:    rgb(255 255 255 / 0.32);
    --label-quaternary:  rgb(255 255 255 / 0.16);

    /* Surfaces get *lighter* as they stack. */
    --bg:                #0B0B0F;
    --bg-secondary:      #16161C;
    --bg-tertiary:       #202029;
    --bg-grouped:        #0B0B0F;

    --fill:              rgb(255 255 255 / 0.12);
    --fill-secondary:    rgb(255 255 255 / 0.09);
    --fill-tertiary:     rgb(255 255 255 / 0.06);

    --separator:         rgb(255 255 255 / 0.14);
    --separator-opaque:  #2A2A33;

    --success:           #35C77A;
    --warning:           #F0A02E;
    --danger:            #FF6B6E;
    --info:              #9B8CFF;

    --accent-tint:       rgb(155 140 255 / 0.16);
    --accent-tint-hover: rgb(155 140 255 / 0.26);
    --chrome:            rgb(22 22 28 / 0.72);
  }
}
```

**The dark block is declared twice in `globals.css`, and that is deliberate.** The
`@media` copy is scoped `:root:not([data-theme="light"])` and is the default and the
no-JavaScript path; a second `:root[data-theme="dark"]` copy carries an explicit user
choice. `:not([data-theme="light"])` is the whole of what makes an explicit choice win in
*both* directions — without it, a user on a dark OS who picks light still gets dark, which
is the easy half of this to ship broken. The two copies must stay identical, and
`theme.test.ts` asserts that they are, so drift is a test failure rather than one subtly
wrong shade in one mode.

**These ratios are measured, not asserted.** Against `--bg` in each theme:

| Token | Light on `#FFFFFF` | Dark on `#0B0B0F` |
|---|---|---|
| `--accent` | **7.18** | **7.10** |
| `--success` | **6.15** | **8.98** |
| `--warning` | **5.43** | **9.14** |
| `--danger` | **5.47** | **7.09** |
| `--info` | **5.93** | **7.10** |

All clear the 4.5:1 body-text floor (§3), which is why the state colours are darker in
light mode than a status colour usually is — they have to survive being used as *text*,
not only as a dot. If you add a token, measure it and add the row; do not eyeball it.

The three tokens that are *surfaces* rather than text are measured against the text they
carry, composited over `--bg`, because that is the pair a reader actually sees:

| Pair | Light | Dark |
|---|---|---|
| `--on-accent` on `--accent` — the `filled` button | **7.18** | **6.68** |
| `--accent` on `--accent-tint` — the `tinted` button | **5.95** | **5.74** |
| `--accent` on `--accent-tint-hover` — tinted, hovered | **5.21** | **4.73** |
| `--label` on `--chrome` over `--bg` — sidebar and toolbar text | **18.77** | **18.52** |

The tinted-hover row is the tightest at 4.73 and it is the one to watch: deepening the
tint any further to make the hover more obvious would push it under the floor.

**Dark mode is not an inversion.** Dark surfaces get *lighter* as they stack
(`#000` → `#1C1C1E` → `#2C2C2E`) while light surfaces get subtly darker. Inverting a light
theme produces the wrong depth cues. A `[data-theme]` attribute on `<html>` must override
the media query in **both** directions so an explicit user choice wins.

### 2.2 Type

```css
:root {
  --font-sans: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  --font-mono: ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace;

  /* Scale adapted for the desktop: a touch UI sets body at ~17pt for arm's length,
     while a desktop web body sits at 15-16px. The ratios between steps are preserved. */
  --text-large-title: 2.125rem;  /* 34px */
  --text-title-1:     1.75rem;   /* 28px */
  --text-title-2:     1.375rem;  /* 22px */
  --text-title-3:     1.25rem;   /* 20px */
  --text-headline:    1rem;      /* 16px, 600 weight */
  --text-body:        1rem;      /* 16px, 400 */
  --text-callout:     0.9375rem; /* 15px */
  --text-subheadline: 0.875rem;  /* 14px */
  --text-footnote:    0.8125rem; /* 13px */
  --text-caption:     0.75rem;   /* 12px */

  --leading-tight: 1.2;   /* titles */
  --leading-normal: 1.5;  /* UI text */
  --leading-relaxed: 1.6; /* message bodies and document text */

  /* Tracking tightens as size grows — large text set at default tracking reads loose. */
  --tracking-title: -0.022em;
  --tracking-body:  -0.011em;

  /* The measure, as a token rather than a number repeated at each call site. */
  --measure: 46rem;
}
```

**Rules.** Sizes in `rem`, never `px` — that is what lets browser zoom and OS text-size
settings work, and it is the web's stand-in for Dynamic Type. **Never go below
`--text-caption` (12px)** for anything a user must read. Weight carries hierarchy before
size does: a 600-weight headline at body size beats a bigger, lighter one.

Message and document text uses `--leading-relaxed` and a **`max-width: 46rem`** measure.
Line length is a legibility control, not a layout preference: past ~75 characters the eye
loses its place on the return sweep.

### 2.3 Spacing — 8pt rhythm, 4pt half-steps

```css
:root {
  --space-1: 0.25rem;  /*  4px */
  --space-2: 0.5rem;   /*  8px */
  --space-3: 0.75rem;  /* 12px */
  --space-4: 1rem;     /* 16px */
  --space-5: 1.25rem;  /* 20px */
  --space-6: 1.5rem;   /* 24px */
  --space-8: 2rem;     /* 32px */
  --space-10: 2.5rem;  /* 40px */
  --space-12: 3rem;    /* 48px */
  --space-16: 4rem;    /* 64px */
}
```

Every margin, padding and gap comes from this scale. The rhythm is what makes an interface
feel composed rather than assembled, and it is invisible right up until one component
opts out.

### 2.4 Radius, materials, elevation

```css
:root {
  --radius-sm: 6px;    /* tags, small badges */
  --radius-md: 10px;   /* buttons, inputs */
  --radius-lg: 14px;   /* cards, message bubbles */
  --radius-xl: 20px;   /* sheets, modals */
  --radius-full: 9999px;

  /* Materials. Translucency + a saturation boost is what makes chrome read as glass
     rather than as a grey box: the saturate() does as much work as the blur. */
  --material-thin:    saturate(180%) blur(20px);
  --material-regular: saturate(180%) blur(30px);
  --material-thick:   saturate(180%) blur(40px);

  /* Elevation is deliberately restrained: material and hairlines separate layers first,
     shadow last. A heavy drop shadow belongs to a different design language. */
  --shadow-sm: 0 1px 2px rgb(0 0 0 / 0.04), 0 1px 3px rgb(0 0 0 / 0.06);
  --shadow-md: 0 2px 8px rgb(0 0 0 / 0.06), 0 4px 16px rgb(0 0 0 / 0.08);
  --shadow-lg: 0 8px 32px rgb(0 0 0 / 0.12);
}
```

**Corner radius is not a squircle.** The continuous-curvature corners you see on Apple
platforms are not what CSS `border-radius` draws — it is a circular arc, and will always
look marginally tighter. Do not try to
fake it with SVG masks on ordinary components — the cost is not worth it. Just prefer
slightly larger radii than instinct suggests.

**A material needs a fallback.** `backdrop-filter` is unsupported or disabled in some
contexts, and a translucent bar over unblurred content is illegible. Always pair it:

```css
.toolbar {
  background: rgb(255 255 255 / 0.72);
  backdrop-filter: var(--material-regular);
}
@supports not (backdrop-filter: blur(1px)) {
  .toolbar { background: var(--bg); }   /* opaque, not translucent */
}
```

### 2.5 Motion

```css
:root {
  --ease-standard: cubic-bezier(0.25, 0.1, 0.25, 1);
  --ease-out:      cubic-bezier(0.16, 1, 0.3, 1);   /* things arriving */

  /* A spring as a linear() easing, so a plain CSS transition can have one
     without an animation library. The overshoot peaks at 1.017 and settles —
     enough to read as physical, not enough to read as playful. Framer Motion's
     spring is the answer when a gesture must be interruptible; this is the
     answer when a transition need not be. */
  --ease-spring: linear(
    0, 0.006, 0.025 2.8%, 0.101 6.1%, 0.539 18.9%, 0.721 25.3%, 0.849 31.5%,
    0.937 38.1%, 0.968 41.8%, 0.991 45.7%, 1.006 50.1%, 1.015 55%, 1.017 63.9%,
    1.001
  );

  --duration-fast:   150ms;  /* hover, focus, small state changes */
  --duration-normal: 250ms;  /* panels, sheets, disclosure */
  --duration-slow:   350ms;  /* full-screen transitions */
}
```

Motion is **informative, not ornamental**: it shows where a thing came from and where it
went. An inspector slides in from the right because that is where it lives. Nothing
bounces for personality.

**`prefers-reduced-motion` is mandatory, not a nicety.** For some users motion is a
vestibular trigger. Honour it globally, once:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

### 2.6 Layout and accessibility constants

The three numbers §1 and §3 state in prose, as tokens — so a component and the test that
checks it are reading the same value rather than two copies of it that agree today.

```css
:root {
  --hit-target:      44px;    /* §3, the minimum interactive target */
  --sidebar-width:   260px;   /* §1 */
  --inspector-width: 320px;   /* §1 */
}
```

`--hit-target` is applied through a single `.hit-target` class rather than repeated on
each control, which is what lets `layout.test.tsx` walk every rendered interactive element
and resolve one number.

---

## 3. Accessibility floors — non-negotiable

Requirements, not aspirations. Cheap while a component is being written and expensive to
retrofit across forty of them.

| Floor | Value | Why |
|---|---|---|
| Hit target | **44×44 px minimum** | The long-standing platform figure, and it holds up. A 24px icon button needs padding, not a smaller target |
| Text contrast | **4.5:1** body, **3:1** large (≥24px or ≥19px bold) | WCAG AA. `--label-tertiary` is decorative — never use it for text a user must read |
| Focus | **Always visible.** `:focus-visible` ring, 2px `--accent`, 2px offset | `outline: none` with no replacement makes the app unusable by keyboard |
| Colour alone | **Never the only signal** | "Superseded" needs a label or an icon as well as `--warning`. ~8% of men have a colour-vision deficiency |
| Semantics | Real `<button>`, `<nav>`, `<dialog>`; ARIA only when no element fits | A `<div onClick>` is invisible to a screen reader and unreachable by keyboard |
| Live regions | Streaming responses announce via `aria-live="polite"` | Otherwise a screen-reader user never learns the answer arrived |

---

## 4. Component conventions

- **Buttons.** Three ranks only: `filled` (one primary action per view), `tinted`
  (`--accent` at 12% behind `--accent` text), `plain`. More ranks than that and none of
  them mean anything.
- **Lists.** Grouped-inset style: rounded container on `--bg-secondary`, hairline
  separators **inset to the text origin**, not full-bleed. A small detail, and the one that
  most separates a considered list from a default one.
- **Sheets and modals.** A modal is for a decision that blocks progress. Everything else
  is an inspector or an inline disclosure. Modals need `<dialog>`, focus trapping, `Esc`,
  and focus restored to the trigger on close.
- **Empty states.** Every list gets one: an icon, one line of what goes here, one action.
  An empty pane with no explanation reads as a bug.
- **Loading.** Skeletons that match the final layout, never a centred spinner over a blank
  region — a spinner discards the layout information the user is about to need. For
  streamed text, render tokens as they arrive.
- **Destructive actions.** `--danger`, and confirmation names the specific thing being
  destroyed. "Delete document?" is not good enough; "Delete *Q3 Revenue Policy*?" is.

---

## 5. Frontend stack

Settled, and consistent with the zero-cost constraint (ADAPTATION §1):

| Concern | Choice | Why |
|---|---|---|
| Framework | **Next.js 15** (App Router), TypeScript strict | Already wired in `docker-compose.yml` as the `web` service |
| Styling | **Tailwind CSS v4**, configured from the tokens in §2 | v4 reads CSS custom properties natively, so the tokens above *are* the config — no second source of truth |
| Primitives | **Radix UI** | Unstyled and accessible by construction: focus trapping, keyboard nav and ARIA are the parts most likely to be got wrong by hand |
| Icons | **Lucide** (ISC) | See §0. One icon family, 1.5px stroke, no mixing |
| Motion | **Framer Motion** | Spring physics and a `useReducedMotion` hook that honours §2.5 |
| Data | **TanStack Query** | Caching, revalidation, and request de-duplication against the API |
| State | React state + context; **no global store** until something demands one | |
| Testing | **Vitest** + Testing Library; **Playwright** for the flows that cross the API | Component tests assert on roles and labels, which is also an accessibility check |

**Types come from the backend, never hand-written.** The API publishes OpenAPI at
`/openapi.json`; generate the client. A hand-maintained TypeScript interface mirroring a
Pydantic model is a second source of truth that silently drifts, and the drift surfaces as
a runtime error in front of a user.

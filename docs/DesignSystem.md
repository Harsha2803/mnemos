# Design System

> **Read this before writing any component.** It is the frontend counterpart to
> [`CodingStandards.md`](CodingStandards.md): rules, with the reason attached, because a
> rule whose rationale is unknown gets worked around the first time it is inconvenient.

This is **Mnemos's own design system**. Its discipline came from studying Apple's
[Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines):
tokens as the single source, an 8pt rhythm, semantic colour roles, accessibility floors and
a measured contrast table. That discipline stays. Its **look** does not come from Apple or
from any other product: since 2026-10-22 the identity is drawn from what Mnemos is about.

**The idea: a reading room for provenance.** Mnemos answers from documents and data and
shows where each claim came from: which revision, which passage, what was admitted to the
prompt and what was excluded, which fact superseded which. So the interface borrows from
the things people already use to read with provenance: a well-set book, a scholarly
apparatus, an archive's revision marks. It is calm, precise and editorial. It is not a chat
toy, and it should not be mistaken for any assistant product.

---

## 0. What we keep, what we chose, and what we refuse

**Kept from the HIG study, because each solves a problem this app has:**

| Idea | What we keep | Why |
|---|---|---|
| **Semantic colour** | Roles (`--label-secondary`) rather than literals, labels as opacity over the background | A role survives a redesign; this revamp changed every value and no component |
| **Spatial rhythm** | An 8pt grid with 4pt half-steps | Rhythm is invisible until one component opts out |
| **Accessibility floors** | 44px targets, visible focus, measured contrast, never colour alone | Cheap while a component is written, expensive across forty |
| **Three columns** | Sidebar / content / inspector | It is this product's information architecture (§1) |
| **Motion that explains** | Short, causal, reduced-motion absolute | Motion says where a thing came from |

**Chosen for Mnemos (2026-10-22):**

| Element | Choice | Why |
|---|---|---|
| **Neutrals** | Warm paper (`#FAF7F0`) and ink in light; warm charcoal (`#1A1815`) in dark | Long reading on cool white or blue-black is the default look of every AI app; paper reads as a page |
| **Accent** | **Verdigris** (`#17625A` / `#6FC1B2`): only for what you can act on | One meaningful ink for interaction. No indigo, violet or blue-violet anywhere |
| **Rubric** | An **editor's red** (`#A63D1C` / `#EE9168`): citation numerals, sidenote rules, revision marks, selection | Manuscripts set rubrics in red ink to mark structure. Here it marks provenance, and only provenance |
| **Type** | Source Serif 4 to read, IBM Plex Sans to operate, IBM Plex Mono to identify, all self-hosted ([ADR-0013](ArchitectureDecisionRecords/ADR-0013-self-hosted-type.md)) | The system stack rendered as Arial for most visitors; three roles of text want three faces |
| **Surfaces** | Rules and whitespace group things; small radii; shadow only for what floats | A rounded grey card around everything is the template look this replaces |
| **Icons** | Lucide, sparingly: where a word would be worse (close, disclosure chevrons, status glyphs) | An icon on every nav row and action is noise that makes nothing lead |

**Refused:**

| Not used | Why |
|---|---|
| **SF Pro, SF Symbols, any Apple asset** | Apple's font and symbol licences cover Apple platforms, not web distribution |
| **Purple, indigo or blue-violet; gradients; glow; sparkle icons** | The visual shorthand of generated AI interfaces; none of it carries meaning here |
| **Chat-app vocabulary** | Right-aligned tinted user bubbles, grey assistant blocks, pill composers with round arrow buttons. Mnemos's answer is a document with an apparatus, not a message |
| **Imitating any product** | Not Claude, ChatGPT, Linear, Notion or anything else. The vocabulary comes from books and archives |

---

## 1. The three ideas the system is built on

**The page leads.** The answer, the passage, the document is the loudest thing on screen.
Chrome is typographic and quiet: words and rules rather than boxes and icons. A row does
not need a filled background to be a row.

**Provenance is visible and has its own ink.** Everything that says *where a claim came
from* is set in the rubric: the superscript numeral, the sidenote's rule, the struck old
value beside the new one. A reader learns one colour and can then find every source on
the page by it.

**Weight makes hierarchy.** One thing per region leads, by face, weight or size, and
everything else steps back. Serif for what is read, sans for what is operated, mono caps
for labels and identifiers. When everything is a 44px grey box, nothing leads.

### The layout follows from this

```
┌────────────┬────────────────────────────────────┬──────────────┐
│  Sidebar   │  Content                           │  Inspector   │
│            │                                    │              │
│ wordmark,  │  the answer as reading text,       │  evidence,   │
│ sections,  │  sidenotes in the margin,          │  bundle, SQL │
│ conver-    │  the composer                      │  for the     │
│ sations    │                                    │  selection   │
│            │                                    │              │
│ 260px      │  fluid; text at 36rem + margin     │  320px, or a │
│            │                                    │  slim rail   │
└────────────┴────────────────────────────────────┴──────────────┘
```

The inspector is the feature. It keeps its place on the right and its place in the
reader's mental model; with nothing selected it is a slim rail, not an empty panel.

---

## 2. Tokens

Everything below is a CSS custom property in `frontend/src/app/globals.css`, and the
values here are copied from it. **No component hard-codes a colour, a radius, or a spacing
value.** A magic number in a component is a value that cannot be themed and will drift
from its neighbours.

### 2.1 Colour — semantic, never literal

```css
:root {
  /* Verdigris: what you can act on. Links, buttons, focus. */
  --accent:              #17625A;
  --accent-hover:        #114C45;
  --on-accent:           #FFFDF8;

  /* The rubric: provenance. Citation numerals, sidenote rules, revision
     marks, the current selection. Never a button and never an error. */
  --rubric:              #A63D1C;
  --rubric-tint:         rgb(166 61 28 / 0.12);

  /* Ink at four strengths, as opacity over the paper. */
  --label:               rgb(31 27 22 / 1.00);
  --label-secondary:     rgb(31 27 22 / 0.66);
  --label-tertiary:      rgb(31 27 22 / 0.36);
  --label-quaternary:    rgb(31 27 22 / 0.16);

  /* Paper in stacking order: the page, the desk around it (sidebar,
     inspector), the raised sheet (inputs, popovers). */
  --bg:                  #FAF7F0;
  --bg-secondary:        #F1ECE1;
  --bg-tertiary:         #FFFDF8;
  --bg-grouped:          #F1ECE1;

  --fill:                rgb(31 27 22 / 0.08);
  --fill-secondary:      rgb(31 27 22 / 0.06);
  --fill-tertiary:       rgb(31 27 22 / 0.04);

  --separator:           rgb(31 27 22 / 0.14);
  --separator-opaque:    #DDD6C8;

  /* State: one meaning each, dark enough to read as text. */
  --success:             #3B6A1E;   /* moss: current, succeeded */
  --warning:             #875200;   /* ochre: superseded, degraded, stale */
  --danger:              #A8292E;   /* carmine: denied, failed, revoked */
  --info:                #4A5A6B;   /* slate: system and compiler notes */

  --accent-tint:         rgb(23 98 90 / 0.12);
  --accent-tint-hover:   rgb(23 98 90 / 0.18);

  /* The sticky toolbar's paper. */
  --chrome:              rgb(250 247 240 / 0.88);
}

@media (prefers-color-scheme: dark) {
  :root {
    --accent:            #6FC1B2;
    --accent-hover:      #8ED1C4;
    --on-accent:         #14201D;

    --rubric:            #EE9168;
    --rubric-tint:       rgb(238 145 104 / 0.16);

    --label:             rgb(240 234 222 / 1.00);
    --label-secondary:   rgb(240 234 222 / 0.64);
    --label-tertiary:    rgb(240 234 222 / 0.36);
    --label-quaternary:  rgb(240 234 222 / 0.16);

    /* Warm charcoal, lighter as it stacks. */
    --bg:                #1A1815;
    --bg-secondary:      #221F1B;
    --bg-tertiary:       #2B2823;
    --bg-grouped:        #1A1815;

    --fill:              rgb(240 234 222 / 0.12);
    --fill-secondary:    rgb(240 234 222 / 0.09);
    --fill-tertiary:     rgb(240 234 222 / 0.06);

    --separator:         rgb(240 234 222 / 0.14);
    --separator-opaque:  #37332D;

    --success:           #A4C77B;
    --warning:           #E2B35D;
    --danger:            #F28B82;
    --info:              #A8B5C3;

    --accent-tint:       rgb(111 193 178 / 0.16);
    --accent-tint-hover: rgb(111 193 178 / 0.26);
    --chrome:            rgb(26 24 21 / 0.88);
  }
}
```

**Two inks, two jobs.** If it can be clicked to *do* something, it is verdigris. If it says
*where something came from*, it is the rubric. A citation numeral is both clickable and
provenance; it is set in the rubric because provenance is what the reader is scanning for,
and its hover and focus states are what say it can be clicked. Danger is carmine, a
different hue from the rubric, and never appears without a word or a glyph beside it.

**The dark block is declared twice in `globals.css`, and that is deliberate.** The
`@media` copy is scoped `:root:not([data-theme="light"])` and is the default and the
no-JavaScript path; a second `:root[data-theme="dark"]` copy carries an explicit user
choice. `:not([data-theme="light"])` is the whole of what makes an explicit choice win in
*both* directions — without it, a user on a dark OS who picks light still gets dark, which
is the easy half of this to ship broken. The two copies must stay identical, and
`theme.test.ts` asserts that they are, so drift is a test failure rather than one subtly
wrong shade in one mode.

**These ratios are measured, not asserted** (WCAG relative luminance, composited over the
surface where a token has alpha). Against `--bg` and against `--bg-secondary`, the two
surfaces text actually sits on:

| Token | Light on `#FAF7F0` | Light on `#F1ECE1` | Dark on `#1A1815` | Dark on `#221F1B` |
|---|---|---|---|---|
| `--label` | **16.00** | **14.53** | **14.79** | **13.70** |
| `--label-secondary` | **5.35** | **5.14** | **6.68** | **6.38** |
| `--accent` | **6.70** | **6.08** | **8.39** | **7.77** |
| `--rubric` | **5.94** | **5.39** | **7.50** | **6.94** |
| `--success` | **6.01** | **5.46** | **9.31** | **8.62** |
| `--warning` | **6.06** | **5.51** | **9.14** | **8.47** |
| `--danger` | **6.50** | **5.90** | **7.42** | **6.87** |
| `--info` | **6.62** | **6.01** | **8.49** | **7.86** |

Every row clears the 4.5:1 body-text floor (§3) on both surfaces. `--label-secondary` is
0.66 in light rather than the usual 0.62 because 0.62 measured 4.55 on `--bg-secondary`,
which is too close to the floor to survive a slightly different screen. `--label-tertiary`
(about 2.1 light, 3.3 dark) is decorative: rules, placeholders, disabled glyphs, never text
a user must read. If you add a token, measure it and add the row; do not eyeball it.

Pairs where the surface is itself a token, composited over `--bg`:

| Pair | Light | Dark |
|---|---|---|
| `--on-accent` on `--accent` — the `filled` button | **7.05** | **7.93** |
| `--accent` on `--accent-tint` — the `tinted` button | **5.60** | **6.21** |
| `--accent` on `--accent-tint-hover` — tinted, hovered | **5.09** | **4.92** |
| `--rubric` on `--rubric-tint` — a selected citation | **4.97** | **5.67** |
| `--label` on `--rubric-tint` — selected or highlighted text | **13.38** | **11.19** |
| `--label` on `--chrome` over `--bg` — toolbar text | **16.00** | **14.79** |

The two to watch are the dark tinted-hover (4.92) and the light rubric-on-tint (4.97):
deepening either tint to make a state more obvious would push it toward the floor.

**Dark mode is not an inversion.** Dark surfaces get *lighter* as they stack
(`#1A1815` → `#221F1B` → `#2B2823`) while light surfaces get subtly darker. A
`[data-theme]` attribute on `<html>` must override the media query in **both** directions
so an explicit user choice wins.

### 2.2 Type

```css
:root {
  --font-serif: var(--font-face-serif), "Source Serif 4", Georgia, "Times New Roman", serif;
  --font-sans:  var(--font-face-sans), "IBM Plex Sans", system-ui, "Segoe UI", Roboto, Arial, sans-serif;
  --font-mono:  var(--font-face-mono), "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;

  --text-large-title: 2.125rem;  /* 34px, serif page titles */
  --text-title-1:     1.75rem;   /* 28px */
  --text-title-2:     1.375rem;  /* 22px */
  --text-title-3:     1.25rem;   /* 20px */
  --text-headline:    1rem;      /* 16px, 600 weight */
  --text-body:        1rem;      /* 16px, 400 */
  --text-reading:     1.0625rem; /* 17px, serif answers and passages */
  --text-callout:     0.9375rem; /* 15px */
  --text-subheadline: 0.875rem;  /* 14px */
  --text-footnote:    0.8125rem; /* 13px */
  --text-caption:     0.75rem;   /* 12px, the floor for anything read */

  --leading-tight: 1.2;    /* titles */
  --leading-normal: 1.5;   /* interface text */
  --leading-relaxed: 1.65; /* serif reading text */

  --tracking-title: -0.012em;
  --tracking-body:  0em;
  --tracking-caps:  0.08em;

  --measure: 46rem;
  --measure-reading: 36rem;
  --chat-measure: 64rem;
}
```

**Three faces, three roles** ([ADR-0013](ArchitectureDecisionRecords/ADR-0013-self-hosted-type.md)).
`font-serif` for what is *read*: answers, quoted passages, document excerpts, page titles
and the wordmark. `font-sans` (the body default) for what is *operated*: navigation,
labels, buttons, forms. `font-mono` for what *identifies*: IDs, digests, SQL, page and
character ranges, and the small uppercase labels (`--tracking-caps`) that name a field or
stamp a route. The faces load from committed files (`frontend/src/app/fonts/`, 109 KB in
total), never from a font CDN.

**Rules.** Sizes in `rem`, never `px`, so browser zoom and OS text-size settings work.
**Never go below `--text-caption` (12px)** for anything a user must read. Weight carries
hierarchy before size does. Running serif text uses `--text-reading`, `--leading-relaxed`
and `--measure-reading` (36rem, about 70 characters of Source Serif at 17px): line length
is a legibility control, not a layout preference. Plex and Source Serif are drawn for
default tracking, so body text is not tightened; only display sizes are.

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
  --radius-sm: 2px;    /* stamps, marks, small badges */
  --radius-md: 4px;    /* buttons, inputs */
  --radius-lg: 6px;    /* panels, sheets of content */
  --radius-xl: 10px;   /* dialogs */
  --radius-full: 9999px;

  --material-thin:    saturate(110%) blur(8px);
  --material-regular: saturate(110%) blur(14px);
  --material-thick:   saturate(110%) blur(24px);

  --shadow-sm: 0 1px 2px rgb(20 16 10 / 0.06);
  --shadow-md: 0 2px 6px rgb(20 16 10 / 0.08), 0 8px 24px rgb(20 16 10 / 0.08);
  --shadow-lg: 0 12px 40px rgb(20 16 10 / 0.18);
}
```

**Paper has corners.** Radii are small, and rules and whitespace do the grouping. A
`--radius-full` pill is for a status dot, not for a button or an input.

**One material, for one job.** Only the sticky toolbar is translucent, and only enough
that content scrolling beneath it is sensed rather than read. The sidebar and inspector
are opaque paper (`--bg-secondary`). A material always has its opaque fallback:

```css
.material-chrome {
  background-color: var(--chrome);
  backdrop-filter: var(--material-regular);
}
@supports not (backdrop-filter: blur(1px)) {
  .material-chrome { background-color: var(--bg-secondary); }
}
```

**Shadow is for what floats** (popovers, dialogs, sheets) and nothing else. Nothing that
sits on the page casts one.

### 2.5 Motion

```css
:root {
  --ease-standard: cubic-bezier(0.25, 0.1, 0.25, 1);
  --ease-out:      cubic-bezier(0.16, 1, 0.3, 1);   /* things arriving */

  /* A spring as a linear() easing, so a plain CSS transition can have one
     without an animation library. The overshoot peaks at 1.017 and settles. */
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

Motion is **causal, not ornamental**: the inspector slides from the edge it lives on; a
sidenote fades toward the numeral it belongs to; a disclosure opens from its own heading.
Nothing bounces for personality. All of it is CSS transitions and keyframes on these
tokens; there is no animation library (§5).

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
  An empty pane with no explanation reads as a bug — the user cannot tell "nothing here
  yet" from "this failed to load", and assumes the worse of the two. The action is omitted
  **only** when there is genuinely nothing the user can do yet; a control that does nothing
  is worse than no control, because it reads as a defect rather than as a boundary.
- **Loading.** Skeletons that match the final layout, never a centred spinner over a blank
  region — a spinner discards the layout information the user is about to need. For
  streamed text, render tokens as they arrive. **Label one skeleton per region, not each
  shape:** six live regions all announcing "loading" is worse than none, so the rest are
  `aria-hidden` decoration.
- **Destructive actions.** `--danger`, and confirmation names the specific thing being
  destroyed. "Delete document?" is not good enough; "Delete *Q3 Revenue Policy*?" is.
- **Appearance.** Three choices, not two: **Match system**, **Light**, **Dark**. "System"
  is a real preference — it means *keep following the OS* — and a light/dark switch throws
  the user's answer away the moment they change their OS setting. The explicit choice is
  stored and stamped on `<html>` as `data-theme` before first paint, and it must win in
  both directions (§2.1). The options are words (System, Light, Dark), each contained in
  its accessible name. It lives in the **account menu**, not the toolbar: it is set once.
- **Navigation.** Typographic: words in three groups separated by space, not an icon per
  row in a grey card. The current item is marked by weight, ink, a short `--rubric` rule
  at its leading edge and `aria-current`, never by colour alone.
- **Row actions.** Secondary actions on a list row (move, rename, delete a conversation)
  appear on hover or when focus enters the row with a fine pointer, and are **always
  visible on a coarse pointer**, where there is no hover to discover them. They sit on the
  row's own opaque surface so nothing shows through. Primary actions are never hidden.
- **Truncation.** A long title, path or ID truncates to one line *and* shows in full on
  hover and on keyboard focus (`Truncate`), as generated content so a text query and a
  screen reader still find it once. Where reading is the point (passages, answers), wrap.
- **Time.** Relative in dense places ("2h", `RelativeTime`), with the exact time as the
  hover title and as text for assistive technology; when the time sits inside a link, it
  is the link's description, not part of its name.
- **An answer is a document, not a bubble.** The question is a compact query line ("YOU"
  in mono caps, then the question in the interface face), with a rule above each new
  exchange. The answer is reading text: serif, `--text-reading`, `--measure-reading`,
  split into its paragraphs. No tinted pills, no grey blocks, no right alignment.
- **Citations are superscript numerals** in the rubric, real buttons, hugging the word
  they cite. On a transcript at least 46rem wide each paragraph's sources sit beside it
  as **sidenotes** (document title, page, the passage's opening lines; a rubric rule when
  active), and a numeral opens the inspector. Below 46rem a numeral opens its source
  **under its paragraph** (`aria-expanded`), with one press on to the inspector. Nothing
  floats over the text being read. Hovering a numeral lights its sidenote and the reverse.
- **The route is a stamp**: mono caps in a 1px border, accent because it is a control,
  revealing "Answered from … and why" on demand.
- **Actions under an answer are a quiet colophon**: words (Inspect, Copy, Bookmark), a
  glyph only for the two ratings, and the latest answer's context budget as a 2px meter
  with its numbers. A failed press is explained at the control (`role="status"`), an
  optimistic change is rolled back, and "Copied" appears where Copy was pressed.
- **Streaming.** The answer fills in place (`aria-busy`). One polite live region says
  "Mnemos is answering." and then "Answer complete." (or stopped, or failed), instead of
  reading tokens aloud. The reader's place is theirs: following the end only while at
  the end, "Jump to latest" when they have scrolled up. A failed answer is labelled
  "Not answered" and offers "Ask again".
- **The composer** is a sheet, not a pill: the textarea, then a line saying how to send
  and that Mnemos chooses documents, data or a tool, and worded Send / Stop buttons.
- **Inline hit areas.** A control that must sit inside a line of text (a numeral, a
  stamp) keeps its visual size and takes a 44px invisible hit area (`.hit-area-inline`),
  so the §3 floor holds without breaking the line.
- **Supersession is a revision mark, not a badge** (`RevisionMark`): the old value struck
  through in the rubric, an arrow, the new value on a rubric tint, and the date it took
  effect. `<del>`/`<ins>` carry the meaning and each half also says it in words
  ("Superseded:", "Replaced by:") for screen readers that do not announce them. Used for
  memory claims, document lineage and conflicts demoted by the compiler.
- **Inspector views** read like an apparatus, not a dashboard: mono caps labels name each
  field, rules separate entries, no tinted cards. Evidence lists each passage with its
  numeral, document title and page; a citation is the document title in serif, its page
  and character range, and the **whole retrieved passage** (the text the model was given)
  with a rubric rule. The bundle shows its budget as a thin bar with exact numbers,
  admitted items with their scores, excluded items struck with the reason in caps, and
  lineage as revision marks.
- **The inspector with nothing selected** is a 48px rail on the right edge, one control
  that opens it to explain itself. A selection opens it fully; leaving the conversation
  clears the selection, because evidence belongs to the answer it was opened from.
---

## 5. Frontend stack

Settled, and consistent with the zero-cost constraint (ADAPTATION §1):

| Concern | Choice | Why |
|---|---|---|
| Framework | **Next.js 15** (App Router), TypeScript strict | Already wired in `docker-compose.yml` as the `web` service |
| Styling | **Tailwind CSS v4**, configured from the tokens in §2 | v4 reads CSS custom properties natively, so the tokens above *are* the config — no second source of truth |
| Primitives | **Radix UI** | Unstyled and accessible by construction: focus trapping, keyboard nav and ARIA are the parts most likely to be got wrong by hand |
| Icons | **Lucide** (ISC) | See §0: sparingly. One icon family, 1.5px stroke, no mixing |
| Fonts | **Source Serif 4, IBM Plex Sans, IBM Plex Mono** (SIL OFL), self-hosted via `next/font/local` | [ADR-0013](ArchitectureDecisionRecords/ADR-0013-self-hosted-type.md); 109 KB, latin, `swap` |
| Motion | **CSS only**: transitions and keyframes on the §2.5 tokens | Every motion here is a short, non-interruptible transition, which CSS does with no dependency and no JavaScript on the main thread; reduced motion is one global block. Framer Motion was listed here until 2026-10-22 but was never installed; add an animation library only for a gesture that must be interruptible, and record why here |
| Data | **TanStack Query** | Caching, revalidation, and request de-duplication against the API |
| State | React state + context; **no global store** until something demands one | |
| Testing | **Vitest** + Testing Library; **Playwright** for the flows that cross the API | Component tests assert on roles and labels, which is also an accessibility check |

**Types come from the backend, never hand-written.** The API publishes OpenAPI at
`/openapi.json`; generate the client. A hand-maintained TypeScript interface mirroring a
Pydantic model is a second source of truth that silently drifts, and the drift surfaces as
a runtime error in front of a user.

---

## 6. Where the system lives (as of `F0`)

The system is implemented, not aspirational. Before adding a component, look at what is
already there — the answer to "what class do I use for a 44px target" is a class that
exists.

| Concern | File |
|---|---|
| Every token in §2, and the only colour literals in the frontend | `frontend/src/app/globals.css` |
| The Tailwind theme mapping (`@theme inline`, and the `--color-*: initial` reset) | same file, lower half |
| `.hit-target`, `.material-chrome`, `.measure`, `.list-group` / `.list-row` | same file, `@layer components` |
| Theme preference, the pre-paint script, the store | `frontend/src/lib/theme.ts` |
| `Button`, `List`, `EmptyState`, `Skeleton`, `Table` | `frontend/src/components/ui/` |
| `ThemeToggle` (rendered inside `AccountMenu`) | `frontend/src/components/theme/` |
| `AccountMenu`, `SidebarContent`, the inspector rail, `ToolbarTitle` | `frontend/src/components/shell/` |
| `Truncate`, `RelativeTime` (and `lib/time.ts` for the wording), `RevisionMark` | `frontend/src/components/ui/` |
| The three-column shell and the breakpoint sheets | `frontend/src/components/shell/AppShell.tsx` |
| Generated API types (never hand-edited; `npm run generate:api`) | `frontend/src/lib/api/schema.ts` |

**Three tests hold the system together, and they are the ones to keep working rather than
to route around:**

- `test_no_component_hardcodes_a_colour` — greps every component source for a hex literal
  and for `rgb(`/`hsl(`. Crude, and it is what keeps §2 true after the twentieth component.
- `test_every_token_in_the_design_system_is_defined_in_globals_css` — parses §2 of *this
  document* and fails on any token the CSS does not define. A token documented but missing
  is a literal waiting to be written, so **adding a token here without adding it there is a
  build failure**, which is the intended direction of pressure.
- `test_every_interactive_target_is_at_least_44px` — resolves `min-height`/`min-width`
  through `--hit-target` from the compiled stylesheet. A new control that skips
  `.hit-target` fails it.

**jsdom cannot evaluate `prefers-color-scheme`, layout, or cascade layers.** The test
harness (`frontend/src/test/harness.ts`) flattens the layers so `getComputedStyle` returns
real values, and the halves it still cannot reach — the media block's scope, the rendered
column widths, the absence of a theme flash — were confirmed in headless Chrome. From
`M3.4`, Playwright is where that belongs.

## 7. Mobile-first layout (2026-09-10)

The [BrowserStack mobile-first guide](https://www.browserstack.com/guide/how-to-implement-mobile-first-design)
provides the approach: prioritize the primary task on small screens, use fluid layouts,
make touch controls accessible, and progressively add detail where space permits.

- The server starts with one content column. Navigation becomes inline at 768px; the
  inspector becomes inline at 1280px. Panel width caps protect the content between them.
  Appearance lives in the account menu at every width; the toolbar keeps navigation,
  location (section, and the conversation's title) and inspection. Both sheets have explicit close buttons, Escape, focus containment and
  focus restoration. Selecting evidence opens its inspector; resizing alone does not.
- `@container/content` on the content pane drives page grids (`@xl/content`, 36rem), so
  open sidebars cannot trick a form into using a desktop grid in a narrow pane. Base grids
  have one `minmax(0, 1fr)` track. Use `min-w-0` for flex/grid children with long content.
- `Table` uses one semantic table and one set of controls. Below its own 40rem container
  width, cells stack as labelled fields; above it, normal columns support comparison.
  Explicit table/row/cell roles preserve semantics when CSS changes display. Headers stay
  in the accessibility tree; repeated visual field labels are `aria-hidden`. Documents,
  source items, query results and audit events share this primitive.
- Inputs use `--text-body` (16px at default scale) regardless of surrounding metadata.
  Interactive targets remain at least 44px. Long paths, identifiers and passages wrap;
  SQL/code may scroll within its own bounded region. Primary actions need no hover.
- The chat transcript owns its scroll; the composer occupies a fixed flex sibling with
  `min-height: 0` ancestors. Dynamic viewport height, safe-area padding and the viewport's
  `interactive-widget=resizes-content` hint keep controls available as browser chrome or
  the supported software keyboard changes the viewport. Pinch zoom remains enabled.
- Source registration is disclosed on demand when sources exist. The selection bar stays
  at the bottom of the item browser; filtering retains selection, switching source resets
  it. Overview quick actions precede operational metrics.
- Browser coverage: `npm run test:responsive` starts a frontend at port 3001 and uses
  deterministic API-boundary fixtures at 320, 390, 768 and 1440px, plus short chat
  viewports. Set `MNEMOS_RESPONSIVE_URL` to use an existing server. Run the separate
  `npm run test:e2e` suite against Compose for real authentication, streaming and
  ingestion. Emulation is not real-device certification; iOS Safari/Android keyboard and
  safe-area checks remain manual QA.
- Screenshots: `npm run screens` renders every main screen at 390 and 1440px in light and
  dark against the fixtures in `frontend/screens/` and writes them to `docs/screens/`.
  Re-run it with any visual change and commit the files that moved, so the pull request
  shows the before and after.

No additional visual assets, UI framework or runtime dependency is needed. The three
committed font files (ADR-0013) are the only webfonts.

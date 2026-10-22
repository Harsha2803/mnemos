# Fonts

Self-hosted through `next/font/local` (`src/app/fonts.ts`), so no request ever leaves for a
font CDN at runtime or at build time. Latin subset only; `font-display: swap`.
Why these and not the system stack: `docs/ArchitectureDecisionRecords/ADR-0013-self-hosted-type.md`.

| File | Family | Use | Bytes | Licence |
|---|---|---|---|---|
| `source-serif-4-latin-wght.woff2` | Source Serif 4, variable weight | answers and document text | 50,936 | SIL OFL 1.1, `OFL-source-serif-4.txt` |
| `ibm-plex-sans-latin-wght.woff2` | IBM Plex Sans, variable weight | interface | 45,712 | SIL OFL 1.1, `OFL-ibm-plex-sans.txt` |
| `ibm-plex-mono-latin-400.woff2` | IBM Plex Mono, regular | identifiers, SQL, metadata | 14,708 | SIL OFL 1.1, `OFL-ibm-plex-mono.txt` |

Total: 111,356 bytes. Taken unmodified from the `@fontsource-variable/source-serif-4`
5.3.1, `@fontsource-variable/ibm-plex-sans` 5.3.0 and `@fontsource/ibm-plex-mono` 5.3.0
npm packages. Adding a weight, a style or a subset is a change to the budget in the ADR.

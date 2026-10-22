# Screens

What the frontend looks like, captured by `npm run screens` in `frontend/`
(`frontend/screens/screens.spec.ts`, fixtures in `frontend/screens/fixtures.ts`).

Each file is `<width>-<scheme>-<screen>.jpg`:

| Width | Viewport |
|---|---|
| `phone` | 390 × 844, touch |
| `desktop` | 1440 × 900 |

| Screen | Route and state |
|---|---|
| `overview` | `/` |
| `chat` | `/chat/s1`, a two-turn conversation answered from documents |
| `citation` | the same conversation with source 1 opened: in the inspector on a desktop, under its paragraph on a phone |
| `menu` | the account menu open (appearance, sign-out); on a phone, over the navigation sheet |
| `knowledge` | `/knowledge`, including a superseded revision and a document still processing |
| `sources` | `/sources` with a source selected, its items, and running, failed and finished jobs |
| `memory` | `/memory`, scrolled to the claim history with one superseded claim |
| `signin` | `/signin` |

The pictures are rendered against fixed API responses, a pinned clock
(2026-10-22 10:00 UTC), the `en-GB` locale and reduced motion, so a file changes only
when the UI does. Re-run the command after a UI change and commit the files that moved;
the pull request then shows the before and after as an image diff.

Run it against a server that is already up with
`MNEMOS_RESPONSIVE_URL=http://localhost:3001 npm run screens`; otherwise it starts
`npm run dev` on port 3001 and stops it afterwards.

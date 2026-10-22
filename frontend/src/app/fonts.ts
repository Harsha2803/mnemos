import localFont from "next/font/local";

/**
 * The three faces, self-hosted (ADR-0013, `fonts/README.md`).
 *
 * `next/font/local` rather than `next/font/google`: the files are committed, so
 * a build never reaches a font host and a page never does either. Each face
 * exposes a CSS variable that the `--font-*` tokens in `globals.css` lead with,
 * so a component asks for `font-serif`, never for a family name.
 *
 * `swap` because text that waits for a font is text a reader cannot start on;
 * the metric-matched fallback `next/font` generates keeps the swap from
 * reflowing the line.
 */
export const serif = localFont({
  src: "./fonts/source-serif-4-latin-wght.woff2",
  weight: "200 900",
  style: "normal",
  display: "swap",
  variable: "--font-face-serif",
  fallback: ["Georgia", "Times New Roman", "serif"],
});

export const sans = localFont({
  src: "./fonts/ibm-plex-sans-latin-wght.woff2",
  weight: "100 700",
  style: "normal",
  display: "swap",
  variable: "--font-face-sans",
  fallback: ["system-ui", "Segoe UI", "Roboto", "Arial", "sans-serif"],
});

export const mono = localFont({
  src: "./fonts/ibm-plex-mono-latin-400.woff2",
  weight: "400",
  style: "normal",
  display: "swap",
  variable: "--font-face-mono",
  fallback: ["ui-monospace", "Menlo", "Consolas", "monospace"],
});

/** The class list `<html>` carries so every token below it can resolve a face. */
export const FONT_VARIABLES = [serif.variable, sans.variable, mono.variable].join(" ");

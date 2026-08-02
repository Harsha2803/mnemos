import type { Metadata, Viewport } from "next";

import { AppShell } from "@/components/shell/AppShell";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

export const metadata: Metadata = {
  title: "Mnemos",
  description: "An AI workspace chatbot whose context is a compiled artifact.",
};

export const viewport: Viewport = {
  // The shell is a desktop layout that reflows; it must never be zoomed to fit,
  // and pinch-zoom must stay available — disabling it fails WCAG 1.4.4.
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // `suppressHydrationWarning` belongs here and nowhere else: the script below
    // deliberately mutates <html> before React sees the document, so the server
    // markup and the hydrated markup are *meant* to differ by one attribute.
    <html lang="en" suppressHydrationWarning>
      <head>
        {/*
          A blocking inline script, first thing in the head. Anything deferred —
          next/script's beforeInteractive included — runs after the first paint,
          and the user on a dark OS sees a white flash before the theme lands.
          This is the one place in the app that may use dangerouslySetInnerHTML,
          and the content is a build-time constant with no interpolated input.
        */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}

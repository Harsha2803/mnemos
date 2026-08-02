import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Mnemos",
  description:
    "An AI workspace chatbot whose context is a compiled artifact.",
};

export const viewport: Viewport = {
  // The shell is a desktop layout that reflows; it must never be zoomed to fit,
  // and pinch-zoom must stay available (disabling it fails WCAG 1.4.4).
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

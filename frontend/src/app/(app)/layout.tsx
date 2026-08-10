import type { ReactNode } from "react";

import { AuthBoundary } from "@/components/auth/AuthBoundary";
import { AppShell } from "@/components/shell/AppShell";
import { InspectorSelectionProvider } from "@/lib/inspector/SelectionProvider";

/**
 * Everything in this route group is behind the session.
 *
 * A route group (the parenthesised directory) rather than a URL segment: the
 * paths stay `/`, `/chat`, `/knowledge` — the boundary is a fact about the
 * application, not something users should have to see in their address bar.
 * Adding a screen here inherits the boundary; adding one outside it is a
 * deliberate act, which is the right way round.
 */
export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <AuthBoundary>
      {/* Outside `AppShell`, because the shell renders the inspector and the
          page inside it decides what the inspector shows — both ends need the
          same provider above them. */}
      <InspectorSelectionProvider>
        <AppShell>{children}</AppShell>
      </InspectorSelectionProvider>
    </AuthBoundary>
  );
}

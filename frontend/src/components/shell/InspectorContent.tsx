import { Layers } from "lucide-react";

import { EmptyState } from "@/components/ui/EmptyState";

/**
 * The inspector is the feature — the bundle viewer that makes the compiled
 * context legible instead of a claim in a README. It gets a permanent home on
 * the right and collapses rather than disappearing from the mental model
 * (DesignSystem §1).
 *
 * There is nothing to inspect until M4 ports the compiler, so it says exactly
 * that. An empty pane with no explanation reads as a bug, and inventing
 * placeholder bundle rows here would read as a working feature that is not.
 */
export function InspectorContent() {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 shrink-0 items-center border-b border-separator px-4">
        <h2 className="text-subheadline font-semibold text-label">Context</h2>
      </div>
      <div className="flex flex-1 items-center justify-center">
        <EmptyState
          icon={Layers}
          title="No message selected"
          description="Select a message and this panel shows the context bundle behind it: what was admitted, what was excluded and why, and what the budget was spent on."
          headingLevel={3}
        />
      </div>
    </div>
  );
}

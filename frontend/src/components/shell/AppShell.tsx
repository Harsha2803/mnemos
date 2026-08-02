"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as VisuallyHidden from "@radix-ui/react-visually-hidden";
import { PanelLeft, PanelRight } from "lucide-react";
import { usePathname } from "next/navigation";
import { useState, type ReactNode } from "react";

import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Button } from "@/components/ui/Button";

import { destinationFor } from "./destinations";
import { InspectorContent } from "./InspectorContent";
import { SidebarContent } from "./SidebarContent";
import { INSPECTOR_INLINE, SIDEBAR_INLINE, useMediaQuery } from "./useMediaQuery";

const INSPECTOR_ID = "context-inspector";

/**
 * The three-column shell from DesignSystem §1: sidebar, content at a readable
 * measure, inspector. The arrangement is not a stylistic borrowing — it is this
 * product's information architecture, and the inspector is the feature.
 *
 * Below 1024px the inspector stops being a column and becomes a modal sheet;
 * below 768px the sidebar does too. That is a change of *component*, not of
 * width — a sheet traps focus, closes on Esc and restores focus to its trigger,
 * none of which a narrower column does — which is why the breakpoints are read
 * in JavaScript rather than left to CSS.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const inspectorIsInline = useMediaQuery(INSPECTOR_INLINE, true);
  const sidebarIsInline = useMediaQuery(SIDEBAR_INLINE, true);

  // Two states, not one. Pinning the inspector open is a desktop layout
  // preference; opening the sheet is a transient action. Sharing one flag makes
  // the sheet spring open the moment a desktop user narrows their window.
  const [inspectorPinned, setInspectorPinned] = useState(true);
  const [inspectorSheetOpen, setInspectorSheetOpen] = useState(false);
  const [sidebarSheetOpen, setSidebarSheetOpen] = useState(false);

  const inspectorShowing = inspectorIsInline ? inspectorPinned : inspectorSheetOpen;

  return (
    <div className="flex h-dvh overflow-hidden bg-bg text-label">
      {sidebarIsInline && (
        <nav
          aria-label="Workspace"
          className="material-chrome w-[var(--sidebar-width)] shrink-0 overflow-y-auto border-r border-separator"
        >
          <SidebarContent />
        </nav>
      )}

      {/* The scroll container is this column, so the toolbar can be sticky
          inside it and content genuinely passes *under* the material. A toolbar
          that is a flex sibling of a separately scrolling pane is translucent
          over nothing, which is a blur filter costing frames for no effect. */}
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <header className="material-chrome sticky top-0 z-20 flex h-14 shrink-0 items-center gap-2 border-b border-separator px-3">
          {!sidebarIsInline && (
            <Button aria-label="Open navigation" onClick={() => setSidebarSheetOpen(true)}>
              <PanelLeft className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />
            </Button>
          )}

          {/* Read from the same list the sidebar renders, so the bar and the nav
              cannot disagree. A literal here is a lie waiting for the second route. */}
          <span className="text-subheadline font-semibold text-label">
            {destinationFor(pathname)?.label ?? "Mnemos"}
          </span>

          <div className="ml-auto flex items-center gap-2">
            <ThemeToggle />
            <Button
              aria-label={inspectorShowing ? "Hide context inspector" : "Show context inspector"}
              aria-expanded={inspectorShowing}
              aria-controls={inspectorIsInline ? INSPECTOR_ID : undefined}
              onClick={() => {
                if (inspectorIsInline) setInspectorPinned((open) => !open);
                else setInspectorSheetOpen(true);
              }}
            >
              <PanelRight className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />
            </Button>
          </div>
        </header>

        <main className="flex-1">
          {/* The 46rem measure (DesignSystem §2.2). Past ~75 characters the eye
              loses its place on the return sweep. */}
          <div className="measure mx-auto px-6 py-8">{children}</div>
        </main>
      </div>

      {inspectorIsInline && (
        <aside
          id={INSPECTOR_ID}
          aria-label="Context inspector"
          className={[
            "shrink-0 overflow-hidden border-separator bg-bg-secondary",
            "transition-[width] duration-250 ease-spring",
            inspectorPinned ? "w-[var(--inspector-width)] border-l" : "w-0",
          ].join(" ")}
        >
          {inspectorPinned && (
            <div className="h-full w-[var(--inspector-width)]">
              <InspectorContent />
            </div>
          )}
        </aside>
      )}

      {!inspectorIsInline && (
        <Sheet
          side="right"
          title="Context inspector"
          open={inspectorSheetOpen}
          onOpenChange={setInspectorSheetOpen}
          width="var(--inspector-width)"
        >
          <InspectorContent />
        </Sheet>
      )}

      {!sidebarIsInline && (
        <Sheet
          side="left"
          title="Workspace"
          open={sidebarSheetOpen}
          onOpenChange={setSidebarSheetOpen}
          width="var(--sidebar-width)"
        >
          <SidebarContent />
        </Sheet>
      )}
    </div>
  );
}

type SheetProps = {
  side: "left" | "right";
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  width: string;
  children: ReactNode;
};

/**
 * An overlay panel on Radix's Dialog, which brings the parts most likely to be
 * got wrong by hand: focus trapping, Esc, scroll locking, and focus restored to
 * the control that opened it.
 *
 * The title is visually hidden rather than absent. Radix requires one, and the
 * requirement is right — an unnamed dialog is announced as "dialog" and nothing
 * else — but the panel already carries its own visible heading.
 */
function Sheet({ side, title, open, onOpenChange, width, children }: SheetProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-label-quaternary" />
        <Dialog.Content
          aria-label={title}
          style={{ width }}
          className={[
            "fixed inset-y-0 z-40 max-w-[85vw] overflow-y-auto bg-bg-secondary shadow-lg",
            side === "right" ? "right-0 border-l border-separator" : "left-0 border-r border-separator",
          ].join(" ")}
        >
          <VisuallyHidden.Root asChild>
            <Dialog.Title>{title}</Dialog.Title>
          </VisuallyHidden.Root>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { PanelLeft, PanelRight, X } from "lucide-react";
import { usePathname } from "next/navigation";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";

import { ThemeToggle } from "@/components/theme/ThemeToggle";
import { Button } from "@/components/ui/Button";
import { readLayoutPreferences, writeLayoutPreferences } from "@/lib/layoutPreferences";
import { useInspectorSelection } from "@/lib/inspector/SelectionProvider";

import { destinationFor } from "./destinations";
import { InspectorContent } from "./InspectorContent";
import { SidebarContent } from "./SidebarContent";
import { INSPECTOR_INLINE, SIDEBAR_INLINE, useMediaQuery } from "./useMediaQuery";

const SIDEBAR_ID = "workspace-sidebar";
const INSPECTOR_ID = "context-inspector";

// The default width every session starts at — `--sidebar-width` /
// `--inspector-width` (globals.css §3), read once rather than kept in sync
// with the token at every render, since a drag immediately owns the number
// from here on.
const DEFAULT_SIDEBAR_WIDTH = 260;
const DEFAULT_INSPECTOR_WIDTH = 320;

// Narrow enough to still read as a sidebar, wide enough that a session title
// is not all ellipsis; wide enough on the inspector's end that a quoted
// passage has room to breathe, capped so it cannot crowd out the conversation.
const SIDEBAR_MIN_WIDTH = 200;
const SIDEBAR_MAX_WIDTH = 420;
const INSPECTOR_MIN_WIDTH = 260;
const INSPECTOR_MAX_WIDTH = 480;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

/**
 * The three-column shell from DesignSystem §1: sidebar, content at a readable
 * measure, inspector. The arrangement is not a stylistic borrowing — it is this
 * product's information architecture, and the inspector is the feature.
 *
 * Below 1280px the inspector stops being a column and becomes a modal sheet;
 * below 768px the sidebar does too. That is a change of *component*, not of
 * width — a sheet traps focus, closes on Esc and restores focus to its trigger,
 * none of which a narrower column does — which is why the breakpoints are read
 * in JavaScript rather than left to CSS.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const inspectorIsInline = useMediaQuery(INSPECTOR_INLINE, false);
  const sidebarIsInline = useMediaQuery(SIDEBAR_INLINE, false);
  const { selection } = useInspectorSelection();
  const navigationTrigger = useRef<HTMLButtonElement>(null);
  const inspectorTrigger = useRef<HTMLButtonElement>(null);
  const inspectorReturnFocus = useRef<HTMLElement | null>(null);
  const previousSelection = useRef(selection);

  // An open conversation is chrome as much as it is prose (the composer, its
  // flow annotations, `SqlPanel`), so it gets the wider `measure-chat` column and
  // a tighter gutter rather than the `measure`/`px-6 py-8` every other route
  // reads at a document's pace. `/chat` with nothing selected is still the
  // narrow `EmptyState`, hence the trailing slash.
  const isChatSession = pathname?.startsWith("/chat/") === true;

  // Two states, not one, per panel. Pinning a panel open is a desktop layout
  // preference; opening the sheet is a transient action. Sharing one flag makes
  // the sheet spring open the moment a desktop user narrows their window.
  const [sidebarPinned, setSidebarPinned] = useState(true);
  const [sidebarSheetOpen, setSidebarSheetOpen] = useState(false);
  const [inspectorPinned, setInspectorPinned] = useState(true);
  const [inspectorSheetOpen, setInspectorSheetOpen] = useState(false);

  const [sidebarWidth, setSidebarWidth] = useState(DEFAULT_SIDEBAR_WIDTH);
  const [inspectorWidth, setInspectorWidth] = useState(DEFAULT_INSPECTOR_WIDTH);
  const [preferencesHydrated, setPreferencesHydrated] = useState(false);

  // A citation or Inspect action opens its result. Resizing alone must never
  // reopen a dismissed sheet or resurrect an old selection.
  useEffect(() => {
    if (selection !== previousSelection.current && selection !== null) {
      if (inspectorIsInline) setInspectorPinned(true);
      else {
        if (!inspectorSheetOpen) {
          inspectorReturnFocus.current = document.activeElement as HTMLElement;
        }
        setInspectorSheetOpen(true);
      }
    }
    previousSelection.current = selection;
  }, [selection, inspectorIsInline, inspectorSheetOpen]);

  useEffect(() => {
    setSidebarSheetOpen(false);
    setInspectorSheetOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (sidebarIsInline) setSidebarSheetOpen(false);
    if (inspectorIsInline) setInspectorSheetOpen(false);
  }, [sidebarIsInline, inspectorIsInline]);

  useEffect(() => {
    const saved = readLayoutPreferences();
    if (saved.sidebarPinned !== undefined) setSidebarPinned(saved.sidebarPinned);
    if (saved.inspectorPinned !== undefined) setInspectorPinned(saved.inspectorPinned);
    if (saved.sidebarWidth !== undefined) {
      setSidebarWidth(clamp(saved.sidebarWidth, SIDEBAR_MIN_WIDTH, SIDEBAR_MAX_WIDTH));
    }
    if (saved.inspectorWidth !== undefined) {
      setInspectorWidth(clamp(saved.inspectorWidth, INSPECTOR_MIN_WIDTH, INSPECTOR_MAX_WIDTH));
    }
    setPreferencesHydrated(true);
  }, []);

  useEffect(() => {
    if (!preferencesHydrated) return;
    writeLayoutPreferences({ sidebarPinned, inspectorPinned, sidebarWidth, inspectorWidth });
  }, [preferencesHydrated, sidebarPinned, inspectorPinned, sidebarWidth, inspectorWidth]);

  const sidebarShowing = sidebarIsInline ? sidebarPinned : sidebarSheetOpen;
  const inspectorShowing = inspectorIsInline ? inspectorPinned : inspectorSheetOpen;

  return (
    <div className="workspace-shell flex h-dvh overflow-hidden bg-bg text-label">
      {sidebarIsInline && (
        <nav
          id={SIDEBAR_ID}
          aria-label="Workspace"
          style={{ "--sidebar-width": `${sidebarWidth}px` } as CSSProperties}
          className={[
            "material-chrome shrink-0 overflow-hidden border-separator",
            "transition-[width] duration-250 ease-spring",
            sidebarPinned ? "sidebar-column w-[var(--sidebar-width)] border-r" : "w-0",
          ].join(" ")}
        >
          {sidebarPinned && (
            <div className="h-full overflow-y-auto">
              <SidebarContent />
            </div>
          )}
        </nav>
      )}

      {sidebarIsInline && sidebarPinned && (
        <ResizeHandle
          label="Resize the workspace sidebar"
          width={sidebarWidth}
          min={SIDEBAR_MIN_WIDTH}
          max={SIDEBAR_MAX_WIDTH}
          onChange={setSidebarWidth}
        />
      )}

      {/* The scroll container is this column, so the toolbar can be sticky
          inside it and content genuinely passes *under* the material. A toolbar
          that is a flex sibling of a separately scrolling pane is translucent
          over nothing, which is a blur filter costing frames for no effect. */}
      <div
        className={`flex min-w-0 flex-1 flex-col ${isChatSession ? "overflow-hidden" : "overflow-y-auto"}`}
      >
        <header className="workspace-toolbar material-chrome sticky top-0 z-20 flex min-h-14 shrink-0 items-center gap-2 border-b border-separator px-3">
          <Button
            ref={navigationTrigger}
            aria-label={sidebarShowing ? "Hide navigation" : "Show navigation"}
            aria-expanded={sidebarShowing}
            aria-controls={sidebarIsInline ? SIDEBAR_ID : undefined}
            onClick={() => {
              if (sidebarIsInline) setSidebarPinned((open) => !open);
              else setSidebarSheetOpen(true);
            }}
          >
            <PanelLeft className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />
          </Button>

          {/* Read from the same list the sidebar renders, so the bar and the nav
              cannot disagree. A literal here is a lie waiting for the second route. */}
          <span className="min-w-0 flex-1 truncate text-subheadline font-semibold text-label">
            {destinationFor(pathname)?.label ?? "Mnemos"}
          </span>

          <div className="ml-auto flex shrink-0 items-center gap-2">
            {sidebarIsInline && <ThemeToggle />}
            <Button
              ref={inspectorTrigger}
              aria-label={inspectorShowing ? "Hide context inspector" : "Show context inspector"}
              aria-expanded={inspectorShowing}
              aria-controls={inspectorIsInline ? INSPECTOR_ID : undefined}
              onClick={() => {
                if (inspectorIsInline) setInspectorPinned((open) => !open);
                else {
                  inspectorReturnFocus.current = inspectorTrigger.current;
                  setInspectorSheetOpen(true);
                }
              }}
            >
              <PanelRight className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />
            </Button>
          </div>
        </header>

        <main className={`min-w-0 flex-1 ${isChatSession ? "flex min-h-0 flex-col" : ""}`}>
          {/* The 46rem measure (DesignSystem §2.2). Past ~75 characters the eye
              loses its place on the return sweep. An open conversation reads
              at `measure-chat` instead, with a tighter gutter — see the
              `isChatSession` comment above. */}
          <div
            className={
              isChatSession
                ? "@container/content measure-chat mx-auto flex min-h-0 w-full flex-1 flex-col"
                : "@container/content measure mx-auto w-full px-4 py-4 sm:px-6 sm:py-8"
            }
          >
            {children}
          </div>
        </main>
      </div>

      {inspectorIsInline && inspectorPinned && (
        <ResizeHandle
          label="Resize the context inspector"
          width={inspectorWidth}
          min={INSPECTOR_MIN_WIDTH}
          max={INSPECTOR_MAX_WIDTH}
          onChange={setInspectorWidth}
          invert
        />
      )}

      {inspectorIsInline && (
        <aside
          id={INSPECTOR_ID}
          aria-label="Context inspector"
          style={{ "--inspector-width": `${inspectorWidth}px` } as CSSProperties}
          className={[
            "shrink-0 overflow-hidden border-separator bg-bg-secondary",
            "transition-[width] duration-250 ease-spring",
            inspectorPinned ? "inspector-column w-[var(--inspector-width)] border-l" : "w-0",
          ].join(" ")}
        >
          {inspectorPinned && (
            <div className="h-full">
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
          returnFocus={() => inspectorReturnFocus.current ?? inspectorTrigger.current}
        >
          <InspectorContent headerAction={<SheetClose label="Close context inspector" />} />
        </Sheet>
      )}

      {!sidebarIsInline && (
        <Sheet
          side="left"
          title="Workspace"
          open={sidebarSheetOpen}
          onOpenChange={setSidebarSheetOpen}
          returnFocus={() => navigationTrigger.current}
        >
          <div
            className="h-full"
            onClick={(event) => {
              if ((event.target as HTMLElement).closest("a[href]")) {
                setSidebarSheetOpen(false);
              }
            }}
          >
            <SidebarContent mobile headerAction={<SheetClose label="Close navigation" />} />
          </div>
        </Sheet>
      )}
    </div>
  );
}

type ResizeHandleProps = {
  /** Accessible name — there is no visible label, only a cursor affordance. */
  label: string;
  width: number;
  min: number;
  max: number;
  onChange: (width: number) => void;
  /**
   * The sidebar's handle sits on its trailing edge: dragging right grows it.
   * The inspector's handle sits on its *leading* edge, so the same rightward
   * drag has to shrink it — `invert` is that one sign flip, kept in one place
   * rather than duplicated arithmetic at each call site.
   */
  invert?: boolean;
};

/**
 * A draggable column boundary — the ARIA "window splitter" pattern: a
 * focusable `separator` with `aria-value*` describing the width it controls,
 * so a screen reader announces it as a slider rather than a decorative line.
 * Pointer drag and the arrow keys drive the same `onChange`, clamped the same
 * way, so neither path can push a panel past what the other allows.
 *
 * Not a `<button>`: nothing here is activated, only continuously adjusted,
 * which is exactly what `role="separator"` plus `aria-valuenow` is for.
 */
function ResizeHandle({ label, width, min, max, onChange, invert = false }: ResizeHandleProps) {
  const dragRef = useRef<{ x: number; width: number } | null>(null);

  function apply(delta: number, from: number): void {
    onChange(clamp(from + (invert ? -delta : delta), min, max));
  }

  function onPointerDown(event: PointerEvent<HTMLDivElement>): void {
    dragRef.current = { x: event.clientX, width };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }

  function onPointerMove(event: PointerEvent<HTMLDivElement>): void {
    const drag = dragRef.current;
    if (drag === null) return;
    apply(event.clientX - drag.x, drag.width);
  }

  function onPointerUp(event: PointerEvent<HTMLDivElement>): void {
    dragRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    const STEP = 16;
    if (event.key === "ArrowLeft") apply(-STEP, width);
    else if (event.key === "ArrowRight") apply(STEP, width);
    else return;
    event.preventDefault();
  }

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(width)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onKeyDown={onKeyDown}
      className={[
        "w-1 shrink-0 cursor-col-resize touch-none select-none",
        "transition-colors duration-150 ease-standard",
        "hover:bg-accent-tint focus-visible:bg-accent-tint-hover active:bg-accent-tint-hover",
      ].join(" ")}
    />
  );
}

type SheetProps = {
  side: "left" | "right";
  title: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  returnFocus: () => HTMLElement | null;
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
function Sheet({ side, title, open, onOpenChange, returnFocus, children }: SheetProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-30 bg-label-quaternary" />
        <Dialog.Content
          aria-label={title}
          aria-describedby={undefined}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            const target = returnFocus();
            if (target?.isConnected) target.focus();
          }}
          className={[
            "workspace-sheet fixed inset-y-0 z-40 w-full overflow-y-auto bg-bg-secondary shadow-lg",
            side === "right" ? "max-w-md" : "max-w-sm",
            side === "right"
              ? "right-0 border-l border-separator"
              : "left-0 border-r border-separator",
          ].join(" ")}
        >
          <Dialog.Title className="sr-only">{title}</Dialog.Title>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function SheetClose({ label }: { label: string }) {
  return (
    <Dialog.Close asChild>
      <Button aria-label={label} className="!px-2">
        <X className="size-5" aria-hidden="true" />
      </Button>
    </Dialog.Close>
  );
}

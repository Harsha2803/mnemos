"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

import type { Citation } from "@/lib/knowledge/api";
import type { Nl2SqlResult } from "@/lib/chat/stream";

/**
 * What the inspector is currently showing.
 *
 * A context rather than props because the two ends are on opposite sides of
 * the layout: `AppShell` renders the inspector, and the page inside it decides
 * what to inspect. Threading a callback down through the shell would make
 * every future page that inspects nothing carry the prop anyway.
 *
 * `A2` puts one thing in here — a citation's source passage. `C4` replaces it
 * with the full context bundle, which is why the value is a named union rather
 * than a bare `Citation | null`.
 */
export type InspectorMessage = {
  id: string;
  content: string;
  citations: Citation[];
  nl2sql?: Nl2SqlResult;
};

export type InspectorSelection =
  | { kind: "message"; message: InspectorMessage }
  | { kind: "citation"; message: InspectorMessage; citation: Citation }
  | { kind: "sql"; message: InspectorMessage; result: Nl2SqlResult }
  | { kind: "bundle"; message: InspectorMessage }
  | null;

type InspectorContextValue = {
  selection: InspectorSelection;
  select: (selection: InspectorSelection) => void;
};

const InspectorContext = createContext<InspectorContextValue | null>(null);

export function InspectorSelectionProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState<InspectorSelection>(null);
  const value = useMemo(() => ({ selection, select: setSelection }), [selection]);
  return <InspectorContext.Provider value={value}>{children}</InspectorContext.Provider>;
}

export function useInspectorSelection(): InspectorContextValue {
  const value = useContext(InspectorContext);
  if (value === null) {
    throw new Error("useInspectorSelection must be used inside InspectorSelectionProvider");
  }
  return value;
}

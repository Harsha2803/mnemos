export type LayoutPreferences = {
  sidebarPinned: boolean;
  inspectorPinned: boolean;
  sidebarWidth: number;
  inspectorWidth: number;
};

export const LAYOUT_STORAGE_KEY = "mnemos.layout";

export function readLayoutPreferences(): Partial<LayoutPreferences> {
  try {
    const parsed: unknown = JSON.parse(window.localStorage.getItem(LAYOUT_STORAGE_KEY) ?? "null");
    if (typeof parsed !== "object" || parsed === null) return {};
    const value = parsed as Record<string, unknown>;
    return {
      sidebarPinned: typeof value.sidebarPinned === "boolean" ? value.sidebarPinned : undefined,
      inspectorPinned: typeof value.inspectorPinned === "boolean" ? value.inspectorPinned : undefined,
      sidebarWidth: typeof value.sidebarWidth === "number" ? value.sidebarWidth : undefined,
      inspectorWidth: typeof value.inspectorWidth === "number" ? value.inspectorWidth : undefined,
    };
  } catch {
    return {};
  }
}

export function writeLayoutPreferences(preferences: LayoutPreferences): void {
  try {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(preferences));
  } catch {
    // A blocked storage context still gets fully working panels for this tab.
  }
}

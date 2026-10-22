"use client";

import * as ToggleGroup from "@radix-ui/react-toggle-group";

import { isThemePreference, setPreference, type ThemePreference } from "@/lib/theme";

import { useThemePreference } from "./useThemePreference";

type Option = {
  value: ThemePreference;
  /** The accessible name. */
  label: string;
  /** The visible word, always contained in `label` (WCAG 2.5.3). */
  short: string;
};

/**
 * "Match system" is offered first and named, rather than being the unlabelled
 * absence of a choice. It is the default, and a user who wants to go back to it
 * needs somewhere to click.
 */
const OPTIONS: readonly Option[] = [
  { value: "system", label: "Match system", short: "System" },
  { value: "light", label: "Light", short: "Light" },
  { value: "dark", label: "Dark", short: "Dark" },
];

/**
 * Three ranked choices, on Radix's ToggleGroup so roving focus and the
 * radiogroup semantics come from a component that has already got them right.
 *
 * Words, not a sun and a moon: a glyph is not self-evident to everyone and is
 * nothing at all to a screen reader. It sits in the account menu (`AccountMenu`),
 * not the toolbar, because it is set once and rarely revisited.
 */
export function ThemeToggle() {
  const preference = useThemePreference();

  return (
    <ToggleGroup.Root
      type="single"
      value={preference}
      onValueChange={(next) => {
        // Radix emits "" when the pressed item is toggled off. Appearance always
        // has an answer, so an empty value means "no change", not "no theme".
        if (isThemePreference(next)) setPreference(next);
      }}
      aria-label="Appearance"
      className="grid w-full grid-cols-3 rounded-md border border-separator p-0.5"
    >
      {OPTIONS.map(({ value, label, short }) => (
        <ToggleGroup.Item
          key={value}
          value={value}
          aria-label={label}
          className={[
            "hit-target inline-flex cursor-pointer items-center justify-center rounded-sm px-2",
            "text-footnote text-label-secondary transition-colors duration-150 ease-standard",
            "hover:text-label",
            "data-[state=on]:bg-fill-secondary data-[state=on]:font-semibold data-[state=on]:text-label",
          ].join(" ")}
        >
          {short}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}

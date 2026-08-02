"use client";

import * as ToggleGroup from "@radix-ui/react-toggle-group";
import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";

import { isThemePreference, setPreference, type ThemePreference } from "@/lib/theme";

import { useThemePreference } from "./useThemePreference";

type Option = {
  value: ThemePreference;
  label: string;
  Icon: LucideIcon;
};

/**
 * "Match system" is offered first and named, rather than being the unlabelled
 * absence of a choice. It is the default, and a user who wants to go back to it
 * needs somewhere to click.
 */
const OPTIONS: readonly Option[] = [
  { value: "system", label: "Match system", Icon: Monitor },
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
];

/**
 * Three ranked choices, on Radix's ToggleGroup so roving focus and the
 * radiogroup semantics come from a component that has already got them right.
 *
 * Each option carries a text label as its accessible name, because the icons
 * alone would be the "colour is never the only signal" mistake in another form
 * — a sun and a moon are not self-evident to everyone, and to a screen reader
 * they are nothing at all.
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
      className="inline-flex items-center gap-1 rounded-md bg-fill-tertiary p-1"
    >
      {OPTIONS.map(({ value, label, Icon }) => (
        <ToggleGroup.Item
          key={value}
          value={value}
          aria-label={label}
          className={[
            "hit-target inline-flex cursor-pointer items-center justify-center rounded-md",
            "text-label-secondary transition-colors duration-150 ease-standard",
            "hover:bg-fill-secondary hover:text-label",
            "data-[state=on]:bg-bg data-[state=on]:text-label data-[state=on]:shadow-sm",
          ].join(" ")}
        >
          <Icon className="size-[18px]" strokeWidth={1.5} aria-hidden="true" />
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}

import type { ButtonHTMLAttributes } from "react";

/**
 * Three ranks, and there is no fourth. `filled` is the one primary action in a
 * view; `tinted` is a secondary action that still wants weight; `plain` is
 * everything else. A fourth rank does not add a level of emphasis — it removes
 * one from each of the other three, because emphasis is relative.
 */
export type ButtonRank = "filled" | "tinted" | "plain";

const RANK_CLASSES: Record<ButtonRank, string> = {
  filled: "bg-accent text-on-accent hover:bg-accent-hover",
  tinted: "bg-accent-tint text-accent hover:bg-accent-tint-hover",
  plain: "text-accent hover:bg-fill-tertiary",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  rank?: ButtonRank;
};

export function Button({
  rank = "plain",
  className = "",
  // A <button> inside a <form> submits it unless told otherwise, and that
  // default has cost more accidental navigations than it has ever saved
  // keystrokes. Submitting is opt-in here.
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={[
        // `hit-target` carries the 44x44 floor from DesignSystem §3 for every
        // control at once, so a future icon button cannot quietly opt out.
        "hit-target inline-flex cursor-pointer items-center justify-center gap-2",
        "rounded-md px-4 text-callout font-semibold",
        "transition-[background-color,color,transform] duration-150 ease-standard active:scale-[0.97]",
        "disabled:pointer-events-none disabled:opacity-40",
        RANK_CLASSES[rank],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
      {...rest}
    />
  );
}

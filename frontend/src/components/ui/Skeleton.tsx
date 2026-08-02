export type SkeletonProps = {
  /**
   * Announce this placeholder to assistive technology under the given name.
   *
   * Left off, the shape is `aria-hidden` decoration. That is the right default:
   * a loading region is usually several shapes, and six live regions all saying
   * "loading" is worse than none. Label the one that stands for the region.
   */
  label?: string;
  className?: string;
};

/**
 * A shape the size of the thing that is coming.
 *
 * Never a centred spinner over a blank region — a spinner throws away the
 * layout information the user is about to need, and then the content arrives
 * and everything jumps (DesignSystem §4). `animate-pulse` collapses under
 * `prefers-reduced-motion` through the global block in `globals.css`.
 */
export function Skeleton({ label, className = "" }: SkeletonProps) {
  const shared = ["animate-pulse rounded-md bg-fill-secondary", className]
    .filter(Boolean)
    .join(" ");

  if (label === undefined) {
    return <span aria-hidden="true" className={shared} />;
  }

  return <span role="status" aria-label={label} className={shared} />;
}

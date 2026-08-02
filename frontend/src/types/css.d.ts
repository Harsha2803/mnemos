/**
 * Vite's `?inline` query returns a stylesheet as the *compiled* CSS string —
 * after PostCSS and Tailwind have run. That is what the tests assert against,
 * because asserting on the source would prove nothing about what ships.
 */
declare module "*.css?inline" {
  const css: string;
  export default css;
}

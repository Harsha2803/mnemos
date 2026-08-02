/**
 * Tailwind v4 is a single PostCSS plugin. There is deliberately no
 * `tailwind.config.js`: the design tokens in `src/app/globals.css` are the
 * configuration (DesignSystem §5, TRACKER C13). A second place to declare a
 * colour is the thing that constraint exists to prevent.
 */
const config = {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};

export default config;

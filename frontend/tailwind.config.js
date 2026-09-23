/** @type {import('tailwindcss').Config} */
// Les couleurs pointent vers les tokens CSS du design system (src/design/tokens.css, brief §9.2).
const v = (name) => `var(--${name})`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: v("color-bg"), surface: v("color-surface"), "surface-2": v("color-surface-2"),
        text: v("color-text"), muted: v("color-text-muted"), border: v("color-border"),
        primary: v("color-primary"), "primary-hover": v("color-primary-hover"),
        accent: v("color-accent"), danger: v("color-danger"), success: v("color-success"),
        "wave-original": v("color-wave-original"), "wave-dubbed": v("color-wave-dubbed"),
      },
      fontFamily: { ui: v("font-ui"), mono: v("font-mono") },
      fontSize: { xs: v("text-xs"), sm: v("text-sm"), md: v("text-md"), lg: v("text-lg"), xl: v("text-xl"), "2xl": v("text-2xl") },
      borderRadius: { sm: v("radius-sm"), md: v("radius-md"), lg: v("radius-lg") },
      boxShadow: { sm: v("shadow-sm"), md: v("shadow-md") },
    },
  },
  plugins: [],
};

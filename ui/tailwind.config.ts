import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

const v = (name: string) => `var(--${name})`;

const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./hooks/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: v("bg"),
        panel: v("panel"),
        ink: v("ink"),
        muted: v("muted"),
        line: v("line"),
        valid: v("valid"),
        stale: v("stale"),
        rebuilding: v("rebuilding"),
        retracted: v("retracted"),
        cutoff: v("cutoff"),
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
      },
    },
  },
  plugins: [animate],
};
export default config;

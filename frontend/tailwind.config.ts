import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: {
          950: "#0a0a0b",
          900: "#111113",
          800: "#191a1d",
          700: "#232428",
          600: "#3a3c42",
        },
        signal: {
          DEFAULT: "#ff6b35",
          soft: "#ff8f66",
        },
        rise: "#3ecf8e",
        fall: "#ef5f5f",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Inter", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;

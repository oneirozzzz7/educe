import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#6366F1",
          light: "#EEF2FF",
          hover: "#4F46E5",
          50: "#EEF2FF",
          100: "#E0E7FF",
          500: "#6366F1",
          600: "#4F46E5",
          700: "#4338CA",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "PingFang SC",
          "Noto Sans SC",
          "sans-serif",
        ],
      },
      boxShadow: {
        subtle: "0 1px 2px rgba(0,0,0,0.04)",
        card: "0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04)",
        input: "0 2px 8px rgba(0,0,0,0.06)",
        "input-focus": "0 2px 8px rgba(0,0,0,0.06), 0 0 0 3px rgba(99,102,241,0.1)",
      },
    },
  },
  plugins: [animate],
} satisfies Config;

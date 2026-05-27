import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#050505",
        surface: { DEFAULT: "#0f0f0f", 2: "#1a1a1a", 3: "#2a2a2a" },
        border: { DEFAULT: "rgba(255,255,255,0.06)", bright: "rgba(255,255,255,0.1)" },
        accent: { DEFAULT: "#00d4aa", dim: "rgba(0,212,170,0.08)", glow: "rgba(0,212,170,0.2)" },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "SF Mono", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;

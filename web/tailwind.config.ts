import type { Config } from "tailwindcss";
import animate from "tailwindcss-animate";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#0a0a0c",
        surface: {
          0: "#0f0f12",
          1: "#141418",
          2: "#1a1a1f",
          3: "#222228",
        },
        border: {
          0: "#1e1e24",
          1: "#2a2a32",
          2: "#3a3a44",
        },
        text: {
          0: "#f0ede8",
          1: "#c8c4bc",
          2: "#8a8680",
          3: "#5a5854",
        },
        amber: {
          DEFAULT: "#d4944c",
          bright: "#e8a85c",
          dim: "rgba(212, 148, 76, 0.10)",
          glow: "rgba(212, 148, 76, 0.06)",
        },
        sage: {
          DEFAULT: "#7a9e7e",
          dim: "rgba(122, 158, 126, 0.12)",
        },
        pass: {
          DEFAULT: "#6ec87a",
          dim: "rgba(110, 200, 122, 0.10)",
        },
        fail: {
          DEFAULT: "#d4645c",
          dim: "rgba(212, 100, 92, 0.10)",
        },
      },
      fontFamily: {
        sans: ["Geist", "-apple-system", "system-ui", "Noto Sans SC", "PingFang SC", "sans-serif"],
        display: ["Instrument Serif", "Georgia", "serif"],
        mono: ["Geist Mono", "SF Mono", "monospace"],
        cjk: ["Noto Sans SC", "PingFang SC", "Microsoft YaHei", "sans-serif"],
      },
      boxShadow: {
        subtle: "0 1px 2px rgba(0,0,0,0.2)",
        card: "0 1px 3px rgba(0,0,0,0.3)",
        input: "0 2px 8px rgba(0,0,0,0.3)",
        "input-focus": "0 2px 8px rgba(0,0,0,0.3), 0 0 0 3px rgba(212,148,76,0.1)",
        overlay: "0 20px 60px rgba(0,0,0,0.5)",
      },
    },
  },
  plugins: [animate],
} satisfies Config;

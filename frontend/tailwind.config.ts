import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "SFMono-Regular", "Consolas", "monospace"],
      },
      colors: {
        ink: {
          950: "#07100f",
          900: "#0b1615",
          850: "#10201e",
        },
        mint: {
          300: "#61e8c5",
          400: "#33d6ad",
          500: "#1cb58f",
        },
      },
      boxShadow: {
        panel: "0 24px 70px -36px rgba(0, 0, 0, 0.7)",
      },
    },
  },
  plugins: [],
} satisfies Config;

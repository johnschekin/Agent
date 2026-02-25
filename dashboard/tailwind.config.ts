import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#0A0D10",
        surface: {
          1: "#12161B",
          2: "#1A1F26",
          3: "#232930",
          4: "#2C333B",
        },
        text: {
          primary: "#EDEFF2",
          secondary: "#8B95A5",
          muted: "#5C6670",
          inverse: "#0A0D10",
        },
        accent: {
          blue: "#3B82F6",
          "blue-hover": "#60A5FA",
          green: "#22C55E",
          "green-hover": "#4ADE80",
          red: "#EF4444",
          "red-hover": "#F87171",
          orange: "#F59E0B",
          amber: "#F59E0B",
          purple: "#A855F7",
          teal: "#14B8A6",
          cyan: "#06B6D4",
          pink: "#EC4899",
        },
        glow: {
          blue: "rgba(59,130,246,0.12)",
          green: "rgba(34,197,94,0.12)",
          red: "rgba(239,68,68,0.12)",
          amber: "rgba(245,158,11,0.12)",
          purple: "rgba(168,85,247,0.12)",
          cyan: "rgba(6,182,212,0.12)",
        },
        border: {
          DEFAULT: "#2C333B",
          light: "#3A4250",
          focus: "#3B82F6",
        },
      },
      borderColor: {
        DEFAULT: "#2C333B",
        light: "#3A4250",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["var(--font-jetbrains)", "JetBrains Mono", "SF Mono", "Menlo", "monospace"],
      },
      fontSize: {
        xs: ["12px", { lineHeight: "16px" }],
        sm: ["13px", { lineHeight: "18px" }],
        base: ["14px", { lineHeight: "20px" }],
        lg: ["16px", { lineHeight: "24px" }],
        xl: ["20px", { lineHeight: "28px" }],
        "2xl": ["24px", { lineHeight: "32px" }],
        "3xl": ["30px", { lineHeight: "36px" }],
        "4xl": ["36px", { lineHeight: "40px" }],
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "6px",
        md: "6px",
        lg: "8px",
        xl: "12px",
      },
      spacing: {
        rail: "56px",
        flyout: "240px",
      },
      boxShadow: {
        card: "0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2)",
        raised: "0 4px 12px rgba(0,0,0,0.4), 0 2px 4px rgba(0,0,0,0.3)",
        overlay: "0 8px 24px rgba(0,0,0,0.5), 0 4px 8px rgba(0,0,0,0.35)",
        "glow-blue": "0 0 12px rgba(59,130,246,0.25), 0 0 4px rgba(59,130,246,0.15)",
        "inset-blue": "inset 3px 0 0 #3B82F6",
        "focus-ring": "0 0 0 2px rgba(59,130,246,0.4)",
      },
      keyframes: {
        fadeIn: {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        triageFadeIn: {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        paletteSlideIn: {
          from: { opacity: "0", transform: "translateX(-8px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        batchBarIn: {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        "fade-in": "fadeIn 200ms ease-out",
        "triage-fade-in": "triageFadeIn 200ms ease-out",
        "palette-slide-in": "paletteSlideIn 200ms ease-out",
        "batch-bar-in": "batchBarIn 200ms ease-out",
        shimmer: "shimmer 1.5s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
export default config;

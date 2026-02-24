import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        surface: {
          primary: "#111418",
          secondary: "#1C2127",
          tertiary: "#252A31",
        },
        text: {
          primary: "#EDEFF2",
          secondary: "#738091",
          muted: "#5C6670",
        },
        accent: {
          blue: "#137CBD",
          "blue-hover": "#1A8FD4",
          green: "#27AE60",
          red: "#DB3737",
          orange: "#D9822B",
          purple: "#8F56BF",
          teal: "#00A396",
        },
      },
      borderColor: {
        DEFAULT: "#404854",
        light: "#505A66",
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "system-ui",
          "sans-serif",
        ],
        mono: ["SF Mono", "Menlo", "Monaco", "monospace"],
      },
      fontSize: {
        xs: "11px",
        sm: "13px",
        base: "14px",
        lg: "16px",
        xl: "20px",
        "2xl": "28px",
        "3xl": "36px",
      },
      borderRadius: {
        sm: "3px",
        DEFAULT: "3px",
        md: "4px",
        lg: "6px",
      },
      spacing: {
        sidebar: "240px",
      },
    },
  },
  plugins: [],
};
export default config;

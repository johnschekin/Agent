// Design system color tokens for use in Recharts and D3
export const CHART_COLORS = {
  blue: "#137CBD",
  green: "#27AE60",
  red: "#DB3737",
  orange: "#D9822B",
  purple: "#8F56BF",
  teal: "#00A396",
  cyan: "#00B3D4",
  pink: "#C23E83",
};

// Categorical palette for pie charts, scatter color coding, etc.
export const CATEGORICAL_PALETTE = [
  "#137CBD",
  "#27AE60",
  "#D9822B",
  "#DB3737",
  "#8F56BF",
  "#00A396",
  "#00B3D4",
  "#C23E83",
];

// Severity badge Tailwind classes (shared across Quality, Edge Cases pages)
export const SEVERITY_COLORS: Record<string, string> = {
  high: "bg-accent-red/20 text-accent-red",
  medium: "bg-accent-orange/20 text-accent-orange",
  low: "bg-surface-tertiary text-text-muted",
};

// Chart axis and grid styling
export const CHART_THEME = {
  axisColor: "#738091",
  gridColor: "#404854",
  gridOpacity: 0.3,
  backgroundColor: "#1C2127",
  tooltipBg: "#252A31",
  tooltipBorder: "#404854",
  tooltipText: "#EDEFF2",
};

// Design system color tokens for use in Recharts and D3
export const CHART_COLORS = {
  blue: "#3B82F6",
  green: "#22C55E",
  red: "#EF4444",
  orange: "#F59E0B",
  purple: "#A855F7",
  teal: "#14B8A6",
  cyan: "#06B6D4",
  pink: "#EC4899",
};

// Categorical palette for pie charts, scatter color coding, etc.
export const CATEGORICAL_PALETTE = [
  "#3B82F6",
  "#22C55E",
  "#F59E0B",
  "#EF4444",
  "#A855F7",
  "#14B8A6",
  "#06B6D4",
  "#EC4899",
];

// Severity badge Tailwind classes (shared across Quality, Edge Cases pages)
export const SEVERITY_COLORS: Record<string, string> = {
  high: "bg-glow-red text-accent-red",
  medium: "bg-glow-amber text-accent-orange",
  low: "bg-surface-3 text-text-muted",
};

// Chart axis and grid styling
export const CHART_THEME = {
  axisColor: "#8B95A5",
  gridColor: "#2C333B",
  gridOpacity: 0.4,
  backgroundColor: "#12161B",
  tooltipBg: "#1A1F26",
  tooltipBorder: "#2C333B",
  tooltipText: "#EDEFF2",
};

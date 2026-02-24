const numFmt = new Intl.NumberFormat("en-US");
const currencyFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});
const pctFmt = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

export function formatNumber(n: number | null | undefined): string {
  if (n == null) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 10_000) return `${(n / 1_000).toFixed(1)}K`;
  return numFmt.format(n);
}

export function formatCurrency(n: number | null | undefined): string {
  if (n == null) return "—";
  return currencyFmt.format(n * 1_000_000); // facility_size_mm is in millions
}

export function formatCurrencyMM(n: number | null | undefined): string {
  if (n == null) return "—";
  return `$${numFmt.format(n)}M`;
}

export function formatPercent(n: number | null | undefined): string {
  if (n == null) return "—";
  // API always returns percentages as 0-100 (e.g. 87.3 means 87.3%)
  return `${pctFmt.format(n)}%`;
}

export function formatCompact(n: number | null | undefined): string {
  if (n == null) return "—";
  return numFmt.format(Math.round(n));
}

/**
 * Validate an array of regex patterns. Returns null if all valid,
 * or an error message string describing the first invalid pattern.
 */
export function validateRegexPatterns(patterns: string[]): string | null {
  for (const p of patterns) {
    try {
      new RegExp(p);
    } catch {
      return `Invalid regex: ${p}`;
    }
  }
  return null;
}

/** Format an API error for display. Strips the "API error NNN:" prefix if present. */
export function formatApiError(error: unknown): string {
  if (!error) return "An unknown error occurred.";
  const msg = error instanceof Error ? error.message : String(error);
  // Strip "API error 400: " prefix to show just the detail
  const stripped = msg.replace(/^API error \d+:\s*/, "");
  // Try to extract JSON detail if the server returned {"detail": "..."}
  try {
    const parsed = JSON.parse(stripped);
    if (typeof parsed?.detail === "string") return parsed.detail;
  } catch {
    // not JSON, use as-is
  }
  return stripped || "An unknown error occurred.";
}

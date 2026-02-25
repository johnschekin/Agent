/**
 * Phase 5 E2E: Dashboard tab tests.
 *
 * Tests BatchRunDashboard (KPI cards, family matrix, run-all button,
 * staleness indicator), VintageHeatmap, DriftDiffView, and export button.
 *
 * Verified testids from:
 *   - page.tsx (DashboardTabContent): dashboard-tab, drift-alert-banner,
 *              dashboard-export-btn
 *   - BatchRunDashboard.tsx: batch-run-dashboard, run-all-rules-btn,
 *                            staleness-indicator, family-matrix,
 *                            matrix-family-{id}, matrix-coverage-{id},
 *                            matrix-pending-{id}, run-{run_id}
 *   - VintageHeatmap.tsx: vintage-heatmap, heatmap-cell-{template}-{year},
 *                         heatmap-tooltip
 *   - DriftDiffView.tsx: drift-diff-view, drift-check-{id}, drift-alert-{id},
 *                        ack-drift-{id}, drift-delta-{id}
 *   - ExportImportDialog.tsx: export-import-dialog, export-btn
 *
 * NOTE: KpiCard does NOT have data-testid attributes. The "kpi-*" prefix
 * from the original test was a phantom testid.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Dashboard Tab", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("full");
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
  });

  test("Dashboard tab container renders", async ({ page }) => {
    const dashboardTab = page.locator('[data-testid="dashboard-tab"]');
    await expect(dashboardTab).toBeVisible({ timeout: 5_000 });
    // Should contain "Analytics Dashboard" heading
    await expect(dashboardTab.locator("text=Analytics Dashboard")).toBeVisible();
  });

  test("Batch run dashboard is rendered with KPI cards", async ({ page }) => {
    const dashboard = page.locator('[data-testid="batch-run-dashboard"]');
    await expect(dashboard).toBeVisible({ timeout: 5_000 });
    // KpiCard does not have data-testid, but BatchRunDashboard renders
    // four KpiCards with titles: "Total Links", "Coverage %", "Pending Review", "Drift Alerts"
    await expect(dashboard.locator("text=Total Links")).toBeVisible();
    await expect(dashboard.locator("text=Coverage %")).toBeVisible();
    await expect(dashboard.locator("text=Pending Review")).toBeVisible();
    await expect(dashboard.locator("text=Drift Alerts")).toBeVisible();
  });

  test("Run All Rules button is present and enabled", async ({ page }) => {
    const runAllBtn = page.locator('[data-testid="run-all-rules-btn"]');
    await expect(runAllBtn).toBeVisible({ timeout: 5_000 });
    await expect(runAllBtn).toBeEnabled();
    await expect(runAllBtn).toHaveText("Run All Rules");
  });

  test("Family matrix table renders with rows", async ({ page }) => {
    const matrix = page.locator('[data-testid="family-matrix"]');
    await expect(matrix).toBeVisible({ timeout: 5_000 });
    // Table headers
    await expect(matrix.locator("th", { hasText: "Family" })).toBeVisible();
    await expect(matrix.locator("th", { hasText: "Links" })).toBeVisible();
    await expect(matrix.locator("th", { hasText: "Coverage %" })).toBeVisible();
    // With "full" seed data, there should be at least one family row
    const rows = matrix.locator("tbody tr");
    const count = await rows.count();
    expect(count).toBeGreaterThanOrEqual(1);
    // First row should have a matrix-family-* testid
    const firstRow = matrix.locator('[data-testid^="matrix-family-"]').first();
    await expect(firstRow).toBeVisible();
  });

  test("Staleness indicator shows last batch run time", async ({ page }) => {
    const staleness = page.locator('[data-testid="staleness-indicator"]');
    // Staleness only appears if there are runs
    if (await staleness.isVisible()) {
      const text = await staleness.textContent();
      expect(text).toContain("Last batch run:");
    }
  });

  test("Vintage heatmap is rendered", async ({ page }) => {
    const heatmap = page.locator('[data-testid="vintage-heatmap"]');
    await expect(heatmap).toBeVisible({ timeout: 5_000 });
    // Heatmap has a "Template" header column
    await expect(heatmap.locator("th", { hasText: "Template" })).toBeVisible();
  });

  test("Drift diff view is rendered", async ({ page }) => {
    const driftView = page.locator('[data-testid="drift-diff-view"]');
    await expect(driftView).toBeVisible({ timeout: 5_000 });
    // Should contain "Baseline vs Current" and "Drift Alerts" headings
    await expect(driftView.locator("text=Baseline vs Current")).toBeVisible();
    await expect(driftView.locator("text=Drift Alerts")).toBeVisible();
  });

  test("Export button opens export/import dialog", async ({ page }) => {
    // The actual testid is "dashboard-export-btn" (not "export-btn")
    const exportBtn = page.locator('[data-testid="dashboard-export-btn"]');
    await expect(exportBtn).toBeVisible({ timeout: 5_000 });
    await expect(exportBtn).toHaveText("Export / Import");
    await exportBtn.click();
    // Dialog should appear with testid "export-import-dialog"
    const dialog = page.locator('[data-testid="export-import-dialog"]');
    await expect(dialog).toBeVisible({ timeout: 5_000 });
  });

  test("Drift alert banner appears when there are unacknowledged alerts", async ({ page }) => {
    // The drift-alert-banner is conditionally rendered when unacknowledged alerts exist
    const banner = page.locator('[data-testid="drift-alert-banner"]');
    if (await banner.isVisible()) {
      const text = await banner.textContent();
      expect(text).toContain("drift alert");
    }
  });
});

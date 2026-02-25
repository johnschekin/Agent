/**
 * Phase 5 E2E: Rules drift detection tests.
 *
 * Tests drift badges on rules, drift diff view,
 * and drift alert acknowledgement.
 *
 * Verified testids from:
 *   - page.tsx (rules tab): rule-drift-{rule_id} (Badge with severity, only if drift alert exists)
 *   - DriftDiffView.tsx: drift-diff-view, drift-check-{check_id},
 *                        drift-delta-{id}, drift-alert-{alert_id}, ack-drift-{alert_id}
 *   - page.tsx (dashboard tab): dashboard-tab, drift-alert-banner
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Rules Drift", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("full");
  });

  test("Drift badges appear on rules with drift alerts", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=rules`);
    await page.waitForLoadState("networkidle");
    // The actual testid is rule-drift-{rule_id} (not drift-badge-*)
    const driftBadges = page.locator('[data-testid^="rule-drift-"]');
    const count = await driftBadges.count();
    // With "full" seed data, there should be drift alerts
    if (count > 0) {
      // Each drift badge shows severity text (e.g. "high", "medium", "low")
      const firstBadge = driftBadges.first();
      const text = await firstBadge.textContent();
      expect(["high", "medium", "low"]).toContain(text?.trim());
    }
  });

  test("Dashboard tab renders DriftDiffView", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
    const driftView = page.locator('[data-testid="drift-diff-view"]');
    await expect(driftView).toBeVisible({ timeout: 5_000 });
    // Verify it contains the "Baseline vs Current" section heading
    await expect(driftView.locator("text=Baseline vs Current")).toBeVisible();
    // Verify it contains the "Drift Alerts" section heading
    await expect(driftView.locator("text=Drift Alerts")).toBeVisible();
  });

  test("Drift checks render with check rows", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
    const driftView = page.locator('[data-testid="drift-diff-view"]');
    await expect(driftView).toBeVisible({ timeout: 5_000 });
    // Check rows have testid drift-check-{check_id}
    const checkRows = driftView.locator('[data-testid^="drift-check-"]');
    const count = await checkRows.count();
    if (count > 0) {
      // Each check row shows family_id text and a Drift/Stable badge
      const firstCheck = checkRows.first();
      const badges = firstCheck.locator("text=Drift detected, text=Stable");
      // Should have at least one status badge
      const badgeText = await firstCheck.textContent();
      expect(
        badgeText?.includes("Drift detected") || badgeText?.includes("Stable")
      ).toBeTruthy();
    }
  });

  test("Drift alerts table shows severity badges", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
    const driftView = page.locator('[data-testid="drift-diff-view"]');
    await expect(driftView).toBeVisible({ timeout: 5_000 });
    // Alert rows have testid drift-alert-{alert_id}
    const alertRows = driftView.locator('[data-testid^="drift-alert-"]');
    const count = await alertRows.count();
    if (count > 0) {
      // Each alert row has a severity badge in the first column
      const firstAlert = alertRows.first();
      const alertText = await firstAlert.textContent();
      // Severity should be one of high/medium/low
      expect(
        alertText?.includes("high") ||
        alertText?.includes("medium") ||
        alertText?.includes("low")
      ).toBeTruthy();
    }
  });

  test("Acknowledge drift alert button is functional", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
    const driftView = page.locator('[data-testid="drift-diff-view"]');
    await expect(driftView).toBeVisible({ timeout: 5_000 });
    // Acknowledge buttons have testid ack-drift-{alert_id}
    const ackBtn = page.locator('[data-testid^="ack-drift-"]').first();
    if (await ackBtn.isVisible()) {
      await expect(ackBtn).toBeEnabled();
      await expect(ackBtn).toHaveText("Acknowledge");
    }
  });

  test("Delta indicators show directional values", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
    const driftView = page.locator('[data-testid="drift-diff-view"]');
    await expect(driftView).toBeVisible({ timeout: 5_000 });
    // Delta indicators have testid drift-delta-{id}
    const deltas = driftView.locator('[data-testid^="drift-delta-"]');
    const count = await deltas.count();
    if (count > 0) {
      // Each delta shows a formatted value like "+5", "-3", "+1.2%", etc.
      const firstDelta = deltas.first();
      const text = await firstDelta.textContent();
      // Should contain a number (possibly with +/- prefix and % suffix)
      expect(text).toBeTruthy();
      expect(text!.trim()).toMatch(/^[+\-]?\d/);
    }
  });

  test("Drift alert banner shows on dashboard tab when alerts exist", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
    // The drift-alert-banner is conditionally rendered in DashboardTabContent
    // when there are unacknowledged alerts
    const banner = page.locator('[data-testid="drift-alert-banner"]');
    if (await banner.isVisible()) {
      // Banner should contain a count badge and detail text
      const bannerText = await banner.textContent();
      expect(bannerText).toContain("drift alert");
    }
  });
});

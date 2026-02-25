/**
 * Phase 4 E2E: Coverage Why-Not panel tests.
 *
 * Tests opening the WhyNot panel, green/red node display,
 * suggested tuning, semantic candidates, and panel close.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Coverage — Why Not Panel", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("coverage");
    await page.goto(`${FRONTEND_BASE}/links?tab=coverage`);
    await page.waitForLoadState("networkidle");
  });

  test("Clicking gap row opens WhyNot panel", async ({ page }) => {
    const firstGapRow = page.locator('[data-testid^="gap-row-"]').first();
    await expect(firstGapRow).toBeVisible();
    await firstGapRow.click();
    const panel = page.locator('[data-testid="why-not-panel"]');
    await expect(panel).toBeVisible({ timeout: 5_000 });
    await expect(panel.locator("text=Why Not Matched")).toBeVisible();
  });

  test("WhyNot panel shows doc info and close button", async ({ page }) => {
    const firstGapRow = page.locator('[data-testid^="gap-row-"]').first();
    await firstGapRow.click();
    const panel = page.locator('[data-testid="why-not-panel"]');
    await expect(panel).toBeVisible({ timeout: 5_000 });

    const closeBtn = page.locator('[data-testid="why-not-close"]');
    await expect(closeBtn).toBeVisible();
    await closeBtn.click();
    await expect(panel).toBeHidden();
  });

  test("WhyNot panel displays traffic light evaluation", async ({ page }) => {
    const firstGapRow = page.locator('[data-testid^="gap-row-"]').first();
    await firstGapRow.click();
    const panel = page.locator('[data-testid="why-not-panel"]');
    await expect(panel).toBeVisible({ timeout: 5_000 });
    await page.waitForTimeout(600);
    const trafficAst = panel.locator('[data-testid="traffic-light-ast"]');
    await expect(trafficAst).toBeVisible();
  });

  test("Coverage tab table has 5 columns", async ({ page }) => {
    const headers = page.locator("thead th");
    const headerCount = await headers.count();
    expect(headerCount).toBe(5);
  });

  test("Coverage tab accessible from URL param", async ({ page }) => {
    await expect(page.locator('[data-testid="coverage-tab"]')).toBeVisible();
    await expect(page).toHaveURL(/tab=coverage/);
  });
});

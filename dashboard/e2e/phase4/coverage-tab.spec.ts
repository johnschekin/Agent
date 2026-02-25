/**
 * Phase 4 E2E: Coverage tab tests.
 *
 * Tests KPI cards, gap table rendering, template grouping,
 * sort order, trivially fixable badges, and semantic candidates.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Coverage Tab", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("coverage");
    await page.goto(`${FRONTEND_BASE}/links?tab=coverage`);
    await page.waitForLoadState("networkidle");
  });

  test("Coverage tab loads with KPI cards", async ({ page }) => {
    await expect(page.locator('[data-testid="coverage-tab"]')).toBeVisible();
    // Should render 3 KPI cards: Total Gaps, Gap by Family, Coverage %
    await expect(page.locator("text=Total Gaps")).toBeVisible();
    await expect(page.locator("text=Coverage %")).toBeVisible();
  });

  test("Gap table renders with correct column headers", async ({ page }) => {
    const headers = page.locator("thead th");
    const headerTexts = await headers.allTextContents();
    const joined = headerTexts.join(" ").toLowerCase();
    expect(joined).toContain("doc");
    expect(joined).toContain("heading");
    expect(joined).toContain("template");
    expect(joined).toContain("nearest");
    // Should have fixable column
    expect(joined).toContain("fixable");
  });

  test("Gap rows display seeded coverage data", async ({ page }) => {
    const rows = page.locator('[data-testid^="gap-row-"]');
    const count = await rows.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });

  test("Template grouping shows group headers", async ({ page }) => {
    // Template group rows have distinct styling (bg-surface-2 or group header class)
    const groupHeaders = page.locator('[data-testid^="template-group-"]');
    // With "coverage" seed, we should have at least one template group
    const groupCount = await groupHeaders.count();
    expect(groupCount).toBeGreaterThanOrEqual(1);
  });

  test("Trivially fixable badges match API payload", async ({ page, apiContext }) => {
    const apiRes = await apiContext.get("/api/links/coverage");
    expect(apiRes.ok()).toBeTruthy();
    const payload = await apiRes.json();
    const gaps = Array.isArray(payload.gaps) ? payload.gaps : [];
    const expectedFixable = gaps.filter((row: Record<string, unknown>) =>
      Boolean(row.is_trivially_fixable),
    ).length;

    const uiFixable = await page.getByText("Trivially fixable").count();
    expect(uiFixable).toBe(expectedFixable);
  });

  test("Clicking gap row selects it", async ({ page }) => {
    const firstGapRow = page.locator('[data-testid^="gap-row-"]').first();
    await expect(firstGapRow).toBeVisible();
    await firstGapRow.click();
    await expect(firstGapRow).toHaveClass(/bg-glow/);
  });
});

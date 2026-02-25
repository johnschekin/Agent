/**
 * Phase 3 E2E: Links page load and tab navigation.
 *
 * Tests that /links page loads correctly, all 7 tabs render,
 * Review is default active, tab switching works, and URL params sync.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Links Page Load", () => {
  test("Page loads with title", async ({ linksPage: page }) => {
    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("All 7 tab buttons render", async ({ linksPage: page }) => {
    const tabs = ["review", "coverage", "query", "conflicts", "rules", "dashboard", "children"];
    for (const tabId of tabs) {
      await expect(page.locator(`[data-testid="tab-${tabId}"]`)).toBeVisible();
    }
  });

  test("Review tab is active by default", async ({ linksPage: page }) => {
    const reviewTab = page.locator('[data-testid="tab-review"]');
    // Active tab has blue border-bottom
    await expect(reviewTab).toHaveClass(/border-b-accent-blue/);
  });

  test("Clicking tab switches panel and updates URL", async ({ linksPage: page }) => {
    // Click Coverage tab
    await page.locator('[data-testid="tab-coverage"]').click();

    // URL should update
    await expect(page).toHaveURL(/tab=coverage/);

    // Coverage tab content should show
    await expect(page.locator('[data-testid="coverage-tab"]')).toBeVisible();

    // Click back to Review
    await page.locator('[data-testid="tab-review"]').click();
    await expect(page).toHaveURL(/tab=review/);
  });

  test("Direct URL /links?tab=conflicts loads correct tab", async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
    await page.goto(`${FRONTEND_BASE}/links?tab=conflicts`);
    await page.waitForLoadState("networkidle");

    const conflictsTab = page.locator('[data-testid="tab-conflicts"]');
    await expect(conflictsTab).toHaveClass(/border-b-accent-blue/);
    await expect(page.locator('[data-testid="conflicts-tab"]')).toBeVisible();
  });

  test("Review tab shows seeded links after fixture reset/seed", async ({ linksPage: page }) => {
    await page.locator('[data-testid="tab-review"]').click();
    await page.waitForSelector("tbody tr", { timeout: 10_000 });
    const rows = page.locator("tbody tr");
    expect(await rows.count()).toBeGreaterThan(0);
  });
});

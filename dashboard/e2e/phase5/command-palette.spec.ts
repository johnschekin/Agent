/**
 * Phase 5 E2E: Command palette tests.
 *
 * Tests Cmd+K opening/closing, fuzzy search, keyboard navigation,
 * result types, footer hints, and navigation on selection.
 *
 * Verified testids from CommandPalette.tsx:
 *   command-palette          — full overlay container (fixed inset-0)
 *   command-palette-input    — search input
 *   command-palette-results  — scrollable results list
 *   palette-item-{type}-{id} — each result button (type = tab|family|rule|action)
 *   command-palette-footer   — footer with keyboard hints
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Command Palette", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
    await page.goto(`${FRONTEND_BASE}/links?tab=review`);
    await page.waitForLoadState("networkidle");
  });

  test("Cmd+K opens command palette", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    const palette = page.locator('[data-testid="command-palette"]');
    await expect(palette).toBeVisible();
    // The overlay should contain the search input and results
    await expect(page.locator('[data-testid="command-palette-input"]')).toBeVisible();
    await expect(page.locator('[data-testid="command-palette-results"]')).toBeVisible();
    await expect(page.locator('[data-testid="command-palette-footer"]')).toBeVisible();
  });

  test("Cmd+K toggles palette closed when open", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    await page.keyboard.press("Meta+k");
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });

  test("Escape closes command palette", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    await expect(page.locator('[data-testid="command-palette"]')).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });

  test("Search input is auto-focused", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    const input = page.locator('[data-testid="command-palette-input"]');
    await expect(input).toBeFocused({ timeout: 3_000 });
    // Input should have the correct placeholder
    await expect(input).toHaveAttribute("placeholder", /Search tabs/);
  });

  test("Results show tab items by default", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    const results = page.locator('[data-testid="command-palette-results"]');
    await expect(results).toBeVisible();
    // 7 tabs + 6 actions + any families from seed = at least 13 items
    const tabItems = page.locator('[data-testid^="palette-item-tab-"]');
    const tabCount = await tabItems.count();
    expect(tabCount).toBe(7);
    // Verify specific tab items exist
    await expect(page.locator('[data-testid="palette-item-tab-review"]')).toBeVisible();
    await expect(page.locator('[data-testid="palette-item-tab-rules"]')).toBeVisible();
    await expect(page.locator('[data-testid="palette-item-tab-dashboard"]')).toBeVisible();
    // Action items should also be present
    const actionItems = page.locator('[data-testid^="palette-item-action-"]');
    const actionCount = await actionItems.count();
    expect(actionCount).toBe(6);
  });

  test("Fuzzy search filters results", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    const input = page.locator('[data-testid="command-palette-input"]');
    await input.fill("rul");
    // Should show the "Rules" tab
    await expect(page.locator('[data-testid="palette-item-tab-rules"]')).toBeVisible();
    // Items that don't match "rul" should be filtered out
    // "Review" doesn't fuzzy-match "rul" (r-u-l in sequence), so check results are filtered
    const visibleItems = page.locator('[data-testid^="palette-item-"]');
    const count = await visibleItems.count();
    expect(count).toBeGreaterThanOrEqual(1);
    expect(count).toBeLessThan(13); // fewer than the full unfiltered set
  });

  test("Clicking backdrop closes palette", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    const palette = page.locator('[data-testid="command-palette"]');
    await expect(palette).toBeVisible();
    // Click on the overlay (outside the modal inner area) to close
    await palette.click({ position: { x: 10, y: 10 } });
    await expect(palette).toBeHidden();
  });

  test("ArrowDown/ArrowUp navigates results and Enter selects", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    const input = page.locator('[data-testid="command-palette-input"]');
    await expect(input).toBeFocused({ timeout: 3_000 });

    // Navigate down twice
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("ArrowDown");

    // The third item (index 2) should have the active highlight (bg-glow-blue)
    const thirdItem = page.locator('[data-testid^="palette-item-"]').nth(2);
    await expect(thirdItem).toHaveClass(/bg-glow-blue/);

    // Navigate back up
    await page.keyboard.press("ArrowUp");
    const secondItem = page.locator('[data-testid^="palette-item-"]').nth(1);
    await expect(secondItem).toHaveClass(/bg-glow-blue/);

    // Enter selects and closes palette
    await page.keyboard.press("Enter");
    await expect(page.locator('[data-testid="command-palette"]')).toBeHidden();
  });

  test("Footer displays keyboard hints", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    const footer = page.locator('[data-testid="command-palette-footer"]');
    await expect(footer).toBeVisible();
    const footerText = await footer.textContent();
    expect(footerText).toContain("Navigate");
    expect(footerText).toContain("Select");
    expect(footerText).toContain("Close");
  });
});

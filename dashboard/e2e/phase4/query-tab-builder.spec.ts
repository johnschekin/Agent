/**
 * Phase 4 E2E: AST Filter Builder tests.
 *
 * Tests the visual AST editor: chip rendering, AND/OR toggle,
 * negate badges, group nesting, and max depth guard.
 */
import { test, expect } from "../fixtures/links-page";

test.describe("Query Tab — AST Builder", () => {
  test.beforeEach(async ({ linksPage: page }) => {
    await page.locator('[data-testid="tab-query"]').click();
    await page.waitForSelector('[data-testid="query-tab"]', { timeout: 5_000 });
  });

  test("AST builder renders with empty state", async ({ linksPage: page }) => {
    await expect(page.locator('[data-testid="ast-builder"]')).toBeVisible();
    await expect(page.locator('[data-testid="ast-builder-init"]')).toBeVisible();
  });

  test("Click init creates root AND group", async ({ linksPage: page }) => {
    await page.locator('[data-testid="ast-builder-init"]').click();
    await expect(page.locator('[data-testid="filter-group-root"]')).toBeVisible();
    await expect(page.locator('[data-testid="toggle-op-root"]')).toContainText("and");
    // Init button should disappear after creating root
    await expect(page.locator('[data-testid="ast-builder-init"]')).toBeHidden();
  });

  test("Add match chip to group", async ({ linksPage: page }) => {
    await page.locator('[data-testid="ast-builder-init"]').click();
    await page.locator('[data-testid="add-match-root"]').click();
    const chip = page.locator('[data-testid="filter-match-children.0"]');
    await expect(chip).toBeVisible();
    // Chip should contain an editable input
    await expect(page.locator('[data-testid="match-input-children.0"]')).toBeVisible();
  });

  test("Toggle AND/OR operator", async ({ linksPage: page }) => {
    await page.locator('[data-testid="ast-builder-init"]').click();
    const toggleBtn = page.locator('[data-testid="toggle-op-root"]');
    await expect(toggleBtn).toContainText("and");
    await toggleBtn.click();
    await expect(toggleBtn).toContainText("or");
    // Toggle back
    await toggleBtn.click();
    await expect(toggleBtn).toContainText("and");
  });

  test("Negate badge shows red indicator", async ({ linksPage: page }) => {
    await page.locator('[data-testid="ast-builder-init"]').click();
    await page.locator('[data-testid="add-match-root"]').click();
    // Toggle negate on
    await page.locator('[data-testid="toggle-negate-children.0"]').click();
    await expect(page.locator('[data-testid="negate-badge-children.0"]')).toBeVisible();
    // Toggle negate off
    await page.locator('[data-testid="toggle-negate-children.0"]').click();
    await expect(page.locator('[data-testid="negate-badge-children.0"]')).toBeHidden();
  });

  test("Remove chip from group", async ({ linksPage: page }) => {
    await page.locator('[data-testid="ast-builder-init"]').click();
    await page.locator('[data-testid="add-match-root"]').click();
    await expect(page.locator('[data-testid="filter-match-children.0"]')).toBeVisible();
    await page.locator('[data-testid="remove-match-children.0"]').click();
    await expect(page.locator('[data-testid="filter-match-children.0"]')).toBeHidden();
  });

  test("Add nested group", async ({ linksPage: page }) => {
    await page.locator('[data-testid="ast-builder-init"]').click();
    await page.locator('[data-testid="add-group-root"]').click();
    const nestedGroup = page.locator('[data-testid="filter-group-children.0"]');
    await expect(nestedGroup).toBeVisible();
    // Nested group should have its own toggle
    await expect(page.locator('[data-testid="toggle-op-children.0"]')).toBeVisible();
    // Nested group should have add-match and add-group buttons
    await expect(page.locator('[data-testid="add-match-children.0"]')).toBeVisible();
  });

  test("Max depth guard prevents exceeding 5 levels", async ({ linksPage: page }) => {
    await page.locator('[data-testid="ast-builder-init"]').click();

    // Add nested groups: root(depth0) -> ... -> depth5
    let currentPath = "root";
    for (let i = 0; i < 5; i++) {
      await page.locator(`[data-testid="add-group-${currentPath}"]`).click();
      currentPath = currentPath === "root" ? "children.0" : `${currentPath}.children.0`;
    }

    // At depth 5, the add-group button should NOT be present
    const deepGroupBtn = page.locator(`[data-testid="add-group-${currentPath}"]`);
    await expect(deepGroupBtn).toHaveCount(0);

    const deepGroup = page.locator(`[data-testid="filter-group-${currentPath}"]`);
    await expect(deepGroup).toBeVisible();
  });

  test("Keyboard: Delete removes focused chip", async ({ linksPage: page }) => {
    await page.locator('[data-testid="ast-builder-init"]').click();
    await page.locator('[data-testid="add-match-root"]').click();
    const chip = page.locator('[data-testid="filter-match-children.0"]');
    await expect(chip).toBeVisible();
    // Focus the chip container and press Delete
    await chip.focus();
    await page.keyboard.press("Delete");
    await expect(chip).toBeHidden();
  });
});

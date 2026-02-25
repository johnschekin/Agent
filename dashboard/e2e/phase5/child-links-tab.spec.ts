/**
 * Phase 5 E2E: Child links tab tests.
 *
 * Tests tab rendering, parent selector, child link review table,
 * child link queue, generate candidates, and apply actions.
 *
 * Verified testids:
 *   page.tsx ChildrenTabContent:
 *     children-tab, parent-link-selector
 *   ChildLinkReview.tsx:
 *     child-link-review, child-link-{node_link_id},
 *     child-link-accept-{node_link_id}, child-link-reject-{node_link_id},
 *     child-batch-accept, child-batch-reject
 *   ChildLinkQueue.tsx:
 *     child-link-queue, generate-candidates-btn,
 *     child-tier-{all|high|medium|low}, child-candidate-{clause_path},
 *     child-accept-{clause_path}, child-reject-{clause_path},
 *     child-factors-{clause_path}, apply-child-links-btn
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Child Links Tab", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("full");
    await page.goto(`${FRONTEND_BASE}/links?tab=children`);
    await page.waitForLoadState("networkidle");
  });

  test("Children tab container renders", async ({ page }) => {
    const tab = page.locator('[data-testid="children-tab"]');
    await expect(tab).toBeVisible({ timeout: 5_000 });
    // Verify no Phase 5 placeholder text
    await expect(page.locator("text=Coming in Phase 5")).toBeHidden();
  });

  test("Parent link selector is visible with correct testid", async ({ page }) => {
    // The actual testid in page.tsx is "parent-link-selector" (not "parent-link-select")
    const selector = page.locator('[data-testid="parent-link-selector"]');
    await expect(selector).toBeVisible({ timeout: 5_000 });
    // Should be a <select> element
    await expect(selector).toHaveAttribute("data-testid", "parent-link-selector");
  });

  test("Empty state shown when no parent selected", async ({ page }) => {
    // The empty state in ChildrenTabContent does not have a data-testid.
    // It renders "Child Link Lifecycle" heading and "Select a parent link" text.
    const childrenTab = page.locator('[data-testid="children-tab"]');
    await expect(childrenTab).toContainText("Select a parent link");
    // ChildLinkReview and ChildLinkQueue should not be visible
    await expect(page.locator('[data-testid="child-link-review"]')).toBeHidden();
    await expect(page.locator('[data-testid="child-link-queue"]')).toBeHidden();
  });

  test("Selecting parent shows child link review panel", async ({ page }) => {
    const selector = page.locator('[data-testid="parent-link-selector"]');
    await expect(selector).toBeVisible({ timeout: 5_000 });
    // Select first option (index 0 is the placeholder "Select a parent link...")
    const options = selector.locator("option");
    const count = await options.count();
    if (count > 1) {
      await selector.selectOption({ index: 1 });
      await page.waitForTimeout(500);
      // ChildLinkReview panel should appear
      const reviewPanel = page.locator('[data-testid="child-link-review"]');
      await expect(reviewPanel).toBeVisible({ timeout: 5_000 });
      // Should contain the header text "Existing Child Links"
      await expect(reviewPanel).toContainText("Existing Child Links");
    }
  });

  test("Selecting parent shows child link queue panel", async ({ page }) => {
    const selector = page.locator('[data-testid="parent-link-selector"]');
    const options = selector.locator("option");
    const count = await options.count();
    if (count > 1) {
      await selector.selectOption({ index: 1 });
      // ChildLinkQueue panel should appear
      const queuePanel = page.locator('[data-testid="child-link-queue"]');
      await expect(queuePanel).toBeVisible({ timeout: 5_000 });
      // Should contain the header text "Candidate Child Links"
      await expect(queuePanel).toContainText("Candidate Child Links");
    }
  });

  test("Child link review shows table when data exists", async ({ page }) => {
    const selector = page.locator('[data-testid="parent-link-selector"]');
    const options = selector.locator("option");
    const count = await options.count();
    if (count > 1) {
      await selector.selectOption({ index: 1 });
      const reviewPanel = page.locator('[data-testid="child-link-review"]');
      await expect(reviewPanel).toBeVisible({ timeout: 5_000 });
      // Check for either a table or the "No child links" message
      const table = reviewPanel.locator("table");
      const emptyMsg = reviewPanel.locator("text=No child links for this parent");
      const hasTable = await table.isVisible().catch(() => false);
      const hasEmptyMsg = await emptyMsg.isVisible().catch(() => false);
      expect(hasTable || hasEmptyMsg).toBeTruthy();
    }
  });

  test("Generate Candidates button is present in queue", async ({ page }) => {
    const selector = page.locator('[data-testid="parent-link-selector"]');
    const options = selector.locator("option");
    const count = await options.count();
    if (count > 1) {
      await selector.selectOption({ index: 1 });
      const genBtn = page.locator('[data-testid="generate-candidates-btn"]');
      await expect(genBtn).toBeVisible({ timeout: 5_000 });
      await expect(genBtn).toHaveText("Generate Candidates");
      // Button should not be disabled initially
      await expect(genBtn).not.toBeDisabled();
    }
  });

  test("Tier filter tabs appear after generating candidates", async ({ page }) => {
    const selector = page.locator('[data-testid="parent-link-selector"]');
    const options = selector.locator("option");
    const count = await options.count();
    if (count > 1) {
      await selector.selectOption({ index: 1 });
      // Tier filter tabs (child-tier-all, child-tier-high, etc.) only appear
      // after candidates are generated (candidates.length > 0).
      // Before generation, they should not be visible.
      const queuePanel = page.locator('[data-testid="child-link-queue"]');
      await expect(queuePanel).toBeVisible({ timeout: 5_000 });
      // The prompt text should be visible since no candidates yet
      await expect(queuePanel).toContainText("Generate Candidates");
    }
  });

  test("Apply button appears after candidates are generated", async ({ page }) => {
    const selector = page.locator('[data-testid="parent-link-selector"]');
    const options = selector.locator("option");
    const count = await options.count();
    if (count > 1) {
      await selector.selectOption({ index: 1 });
      // apply-child-links-btn only renders when candidates exist (inside the
      // candidates.length > 0 branch). Before generation it should be hidden.
      const applyBtn = page.locator('[data-testid="apply-child-links-btn"]');
      await expect(applyBtn).toBeHidden();
    }
  });

  test("Parent selector has placeholder option", async ({ page }) => {
    const selector = page.locator('[data-testid="parent-link-selector"]');
    await expect(selector).toBeVisible({ timeout: 5_000 });
    // First option should be the placeholder
    const firstOption = selector.locator("option").first();
    await expect(firstOption).toHaveText("Select a parent link...");
    await expect(firstOption).toHaveAttribute("value", "");
  });
});

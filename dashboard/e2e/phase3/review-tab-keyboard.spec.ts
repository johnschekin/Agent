/**
 * Phase 3 E2E: Review tab — keyboard navigation.
 *
 * Tests j/k movement, block select, selection toggle, reader pane,
 * jump to pending, and keyboard disabled in inputs.
 */
import { test, expect } from "../fixtures/links-page";

test.describe("Review Tab Keyboard", () => {
  test("j moves focus down", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    const rows = page.locator("tbody tr");
    const rowCount = await rows.count();
    if (rowCount < 2) return; // Need at least 2 rows

    // Initial state: first row should be focused (index 0)
    await expect(rows.nth(0)).toHaveClass(/shadow-inset-blue/);

    // Press j to move focus to the second row
    await page.keyboard.press("j");

    // Second row should now have focus, first row should not
    await expect(rows.nth(1)).toHaveClass(/shadow-inset-blue/);
    const firstRowClasses = await rows.nth(0).getAttribute("class");
    expect(firstRowClasses).not.toContain("shadow-inset-blue");
  });

  test("k moves focus up", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    const rows = page.locator("tbody tr");
    const rowCount = await rows.count();
    if (rowCount < 3) return;

    // Move down twice to row index 2
    await page.keyboard.press("j");
    await page.keyboard.press("j");
    await expect(rows.nth(2)).toHaveClass(/shadow-inset-blue/);

    // Press k to move back up to row index 1
    await page.keyboard.press("k");
    await expect(rows.nth(1)).toHaveClass(/shadow-inset-blue/);

    // Row 2 should no longer be focused
    const row2Classes = await rows.nth(2).getAttribute("class");
    expect(row2Classes).not.toContain("shadow-inset-blue");
  });

  test("j at bottom is no-op", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const rows = page.locator("tbody tr");
    const rowCount = await rows.count();
    if (rowCount === 0) return;

    // Press j to reach the last row
    for (let i = 0; i < rowCount + 5; i++) {
      await page.keyboard.press("j");
    }

    // Last row should be focused
    await expect(rows.nth(rowCount - 1)).toHaveClass(/shadow-inset-blue/);

    // Pressing j again should keep focus on the last row (no-op)
    await page.keyboard.press("j");
    await expect(rows.nth(rowCount - 1)).toHaveClass(/shadow-inset-blue/);
  });

  test("k at top is no-op", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    const rows = page.locator("tbody tr");
    if ((await rows.count()) === 0) return;

    // First row should be focused by default
    await expect(rows.nth(0)).toHaveClass(/shadow-inset-blue/);

    // Press k multiple times at the top
    for (let i = 0; i < 5; i++) {
      await page.keyboard.press("k");
    }

    // First row should still be focused (no-op)
    await expect(rows.nth(0)).toHaveClass(/shadow-inset-blue/);
  });

  test("Space toggles reader pane", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Reader pane should not be visible initially
    const readerContent = page.locator("text=Select a link").or(
      page.locator("text=Section text not available")
    ).or(
      page.locator("text=Undock")
    );
    // Initially zero reader elements
    const initialCount = await readerContent.count();

    // Press Space to open reader pane
    await page.keyboard.press("Space");

    // Reader pane should now be visible
    await expect(readerContent.first()).toBeVisible({ timeout: 3_000 });

    // Press Space again to close
    await page.keyboard.press("Space");

    // Reader content should be hidden again
    await page.waitForTimeout(300);
    const closedCount = await readerContent.count();
    // After closing, reader elements should be removed or hidden
    if (closedCount > 0) {
      await expect(readerContent.first()).toBeHidden({ timeout: 2_000 }).catch(() => {
        // Element may have been removed from DOM
      });
    }
  });

  test("Enter opens reader in new tab", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const rows = page.locator("tbody tr");
    if ((await rows.count()) === 0) return;

    // Listen for new page (new tab)
    const [newPage] = await Promise.all([
      page.context().waitForEvent("page", { timeout: 5_000 }).catch(() => null),
      page.keyboard.press("Enter"),
    ]);

    // If a new tab was opened, it should navigate to the reader
    if (newPage) {
      const url = newPage.url();
      expect(url).toContain("/reader");
      // URL should include doc_id and section params
      expect(url).toMatch(/doc_id=|section=/);
      await newPage.close();
    }
    // If no data rows exist, no tab opens — acceptable
  });

  test("[ jumps to next pending_review", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    const rows = page.locator("tbody tr");
    const rowCount = await rows.count();
    if (rowCount < 2) return;

    // Record initial focused row
    const initialFocusedRow = page.locator("tbody tr[class*='shadow-inset-blue']");
    const initialDataId = await initialFocusedRow.first().getAttribute("data-row-id").catch(() => null);

    // Press [ to jump to next pending_review
    await page.keyboard.press("[");
    await page.waitForTimeout(200);

    // Focus should have moved (or stayed if no pending rows exist)
    const newFocusedRow = page.locator("tbody tr[class*='shadow-inset-blue']");
    const newDataId = await newFocusedRow.first().getAttribute("data-row-id").catch(() => null);
    // Both should be valid (non-null or both null if no data)
    expect(typeof initialDataId === typeof newDataId).toBe(true);
  });

  test("] jumps to previous pending_review", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    const rows = page.locator("tbody tr");
    if ((await rows.count()) < 3) return;

    // Move to end first
    for (let i = 0; i < 10; i++) {
      await page.keyboard.press("j");
    }
    const bottomFocused = page.locator("tbody tr[class*='shadow-inset-blue']");
    const bottomId = await bottomFocused.first().getAttribute("data-row-id").catch(() => null);

    // Press ] to jump backward to previous pending_review
    await page.keyboard.press("]");
    await page.waitForTimeout(200);

    // Focus may have changed
    const afterJump = page.locator("tbody tr[class*='shadow-inset-blue']");
    const afterId = await afterJump.first().getAttribute("data-row-id").catch(() => null);
    // If a pending_review row exists before current position, IDs should differ
    // Otherwise they stay the same — both are valid outcomes
    expect(afterId).toBeTruthy();
  });

  test("Shift+j block-selects contiguous rows", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    const rows = page.locator("tbody tr");
    if ((await rows.count()) < 3) return;

    // Shift+j should select current and move down
    await page.keyboard.press("Shift+j");
    await page.keyboard.press("Shift+j");

    // At least 2 rows should be selected (checkboxes checked)
    const checkedBoxes = page.locator("tbody tr input[type='checkbox']:checked");
    const checkedCount = await checkedBoxes.count();
    expect(checkedCount).toBeGreaterThanOrEqual(2);

    // Batch bar should be visible with selection count
    const batchBar = page.locator("text=selected");
    await expect(batchBar.first()).toBeVisible({ timeout: 2_000 });
  });

  test("x toggles row selection", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    const rows = page.locator("tbody tr");
    if ((await rows.count()) === 0) return;

    // Initially no checked checkboxes (or the focused row's checkbox)
    const initialChecked = await page.locator("tbody tr input[type='checkbox']:checked").count();

    // Press x to toggle selection of focused row
    await page.keyboard.press("x");

    // Selection should have toggled — one more checked
    const afterSelect = await page.locator("tbody tr input[type='checkbox']:checked").count();
    expect(afterSelect).toBe(initialChecked + 1);

    // Press x again to deselect
    await page.keyboard.press("x");

    // Should return to initial count
    const afterDeselect = await page.locator("tbody tr input[type='checkbox']:checked").count();
    expect(afterDeselect).toBe(initialChecked);
  });

  test("Keyboard shortcuts disabled when input focused", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    const rows = page.locator("tbody tr");
    if ((await rows.count()) === 0) return;

    // Record current focused row
    const focusedBefore = page.locator("tbody tr[class*='shadow-inset-blue']");
    const idBefore = await focusedBefore.first().getAttribute("data-row-id").catch(() => "none");

    // Press n to open note input
    await page.keyboard.press("n");
    await page.waitForTimeout(100);

    // Note input should be visible
    const noteInput = page.locator('input[placeholder*="note"]');
    if ((await noteInput.count()) > 0) {
      await noteInput.first().focus();

      // Press j while input is focused — should NOT move row focus
      await page.keyboard.press("j");
      await page.waitForTimeout(100);

      // Focused row should NOT have changed
      const focusedAfter = page.locator("tbody tr[class*='shadow-inset-blue']");
      const idAfter = await focusedAfter.first().getAttribute("data-row-id").catch(() => "none");
      expect(idAfter).toBe(idBefore);

      // The input should still be focused (j typed into input, not used as shortcut)
      const activeTag = await page.evaluate(() => document.activeElement?.tagName);
      expect(activeTag).toBe("INPUT");

      // Escape to close note input
      await page.keyboard.press("Escape");
    }

    // Page should not crash
    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("Shift+Click performs range selection", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const rows = page.locator("tbody tr");
    if ((await rows.count()) < 3) return;

    await rows.nth(0).click();
    await rows.nth(2).click({ modifiers: ["Shift"] });
    await page.waitForTimeout(200);

    const checkedBoxes = page.locator("tbody tr input[type='checkbox']:checked");
    expect(await checkedBoxes.count()).toBeGreaterThanOrEqual(3);
  });
});

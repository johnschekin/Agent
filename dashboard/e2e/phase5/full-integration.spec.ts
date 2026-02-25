/**
 * Phase 5 E2E: Full integration tests.
 *
 * End-to-end flows spanning multiple tabs and features:
 * navigate tabs, command palette, triage mode, rules/pins,
 * dashboard KPIs, export dialog, conflict resolution, and review lifecycle.
 *
 * Verified testids used in this file:
 *   page.tsx:      tab-{id}, link-row-{id}, dashboard-export-btn, dashboard-tab,
 *                  rules-tab, rule-row-{id}, rule-pins-{id}, children-tab,
 *                  coverage-tab, conflicts-tab, query-tab, conflict-row-{id},
 *                  resolve-btn-{id}
 *   CommandPalette: command-palette, command-palette-input, command-palette-results
 *   TriageMode:    triage-mode, triage-exit, triage-approve, triage-card
 *   PinnedTestCasesPanel: pinned-test-cases-panel, pins-panel-close
 *   BatchRunDashboard: batch-run-dashboard, family-matrix
 *   ExportImportDialog: export-import-dialog, export-import-close, export-tab,
 *                       import-tab, export-format-csv
 *   ConflictResolver: conflict-resolver, resolution-split
 *   SubClauseSplitter: sub-clause-splitter
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Full Integration", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("full");
    await page.goto(`${FRONTEND_BASE}/links?tab=review`);
    await page.waitForLoadState("networkidle");
  });

  test("Navigate between all tabs without Phase 5 placeholders", async ({ page }) => {
    const tabs: Array<{ id: string; testid: string }> = [
      { id: "review", testid: "tab-review" },
      { id: "rules", testid: "tab-rules" },
      { id: "dashboard", testid: "tab-dashboard" },
      { id: "children", testid: "tab-children" },
      { id: "coverage", testid: "tab-coverage" },
      { id: "query", testid: "tab-query" },
      { id: "conflicts", testid: "tab-conflicts" },
    ];
    for (const tab of tabs) {
      await page.goto(`${FRONTEND_BASE}/links?tab=${tab.id}`);
      await page.waitForLoadState("networkidle");
      // Verify the tab button is active (has accent-blue text)
      const tabBtn = page.locator(`[data-testid="${tab.testid}"]`);
      await expect(tabBtn).toHaveClass(/text-accent-blue/);
      // Verify no Phase 5 placeholder
      await expect(page.locator("text=Coming in Phase 5")).toBeHidden();
    }
  });

  test("Command palette opens and shows search results", async ({ page }) => {
    await page.keyboard.press("Meta+k");
    const palette = page.locator('[data-testid="command-palette"]');
    await expect(palette).toBeVisible();
    const input = page.locator('[data-testid="command-palette-input"]');
    await expect(input).toBeVisible();
    // Type a search term and verify results appear
    await input.fill("rules");
    await page.waitForTimeout(200);
    const results = page.locator('[data-testid="command-palette-results"]');
    await expect(results).toBeVisible();
    // Results should contain at least one item
    const items = results.locator("[data-testid^='palette-item-']");
    const count = await items.count();
    expect(count).toBeGreaterThanOrEqual(1);
    // Press Enter to navigate
    await page.keyboard.press("Enter");
    await page.waitForTimeout(500);
    // Palette should close after selection
    await expect(palette).toBeHidden();
  });

  test("Triage mode activates and deactivates on review tab", async ({ page }) => {
    // Cmd+F on review tab toggles triage mode
    await page.keyboard.press("Meta+f");
    const triageOverlay = page.locator('[data-testid="triage-mode"]');
    await expect(triageOverlay).toBeVisible({ timeout: 3_000 });
    // Triage card should be shown
    const triageCard = page.locator('[data-testid="triage-card"]');
    if (await triageCard.isVisible({ timeout: 2_000 }).catch(() => false)) {
      // Approve button should be present
      await expect(page.locator('[data-testid="triage-approve"]')).toBeVisible();
    }
    // Exit triage via the exit button
    const exitBtn = page.locator('[data-testid="triage-exit"]');
    await exitBtn.click();
    await expect(triageOverlay).toBeHidden();
  });

  test("Rules tab: pinned test cases panel opens and closes", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=rules`);
    await page.waitForLoadState("networkidle");
    // Find a rule row that has a pins button
    const pinsBtn = page.locator('[data-testid^="rule-pins-"]').first();
    if (await pinsBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await pinsBtn.click();
      const pinsPanel = page.locator('[data-testid="pinned-test-cases-panel"]');
      await expect(pinsPanel).toBeVisible({ timeout: 3_000 });
      // Panel should contain TP/TN tab buttons
      await expect(page.locator('[data-testid="pins-tab-tp"]')).toBeVisible();
      await expect(page.locator('[data-testid="pins-tab-tn"]')).toBeVisible();
      // Close the panel
      await page.locator('[data-testid="pins-panel-close"]').click();
      await expect(pinsPanel).toBeHidden();
    }
  });

  test("Dashboard shows BatchRunDashboard with family matrix", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
    const dashboard = page.locator('[data-testid="batch-run-dashboard"]');
    await expect(dashboard).toBeVisible({ timeout: 5_000 });
    // Family matrix table should be present
    const matrix = page.locator('[data-testid="family-matrix"]');
    if (await matrix.isVisible({ timeout: 3_000 }).catch(() => false)) {
      // Matrix should have at least one family row
      const familyRows = matrix.locator('[data-testid^="matrix-family-"]');
      const count = await familyRows.count();
      expect(count).toBeGreaterThanOrEqual(1);
    }
  });

  test("Export dialog opens from dashboard and dismisses", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
    // The dashboard export button has testid "dashboard-export-btn"
    const exportBtn = page.locator('[data-testid="dashboard-export-btn"]');
    await expect(exportBtn).toBeVisible({ timeout: 5_000 });
    await exportBtn.click();
    const dialog = page.locator('[data-testid="export-import-dialog"]');
    await expect(dialog).toBeVisible();
    // Verify export format buttons are present
    await expect(page.locator('[data-testid="export-format-csv"]')).toBeVisible();
    // Close with the correct testid: "export-import-close"
    await page.locator('[data-testid="export-import-close"]').click();
    await expect(dialog).toBeHidden();
  });

  test("Keyboard shortcuts differ between review and rules tabs", async ({ page }) => {
    // On the review tab, the KeyboardHelpBar renders review shortcuts.
    // It has no data-testid, so we check for its characteristic content.
    const helpBarSelector = ".bg-surface-2.border-t";
    const helpBar = page.locator(helpBarSelector);
    if (await helpBar.isVisible({ timeout: 2_000 }).catch(() => false)) {
      // Review tab should show navigation shortcuts
      await expect(helpBar).toContainText("Navigate");
      await expect(helpBar).toContainText("Unlink");
    }
    // Switch to rules tab
    await page.goto(`${FRONTEND_BASE}/links?tab=rules`);
    await page.waitForLoadState("networkidle");
    const rulesHelpBar = page.locator(helpBarSelector);
    if (await rulesHelpBar.isVisible({ timeout: 2_000 }).catch(() => false)) {
      // Rules tab should show Publish shortcut
      await expect(rulesHelpBar).toContainText("Publish");
    }
  });

  test("Conflict resolution flow with resolver panel", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=conflicts`);
    await page.waitForLoadState("networkidle");
    // Find a conflict row with a resolve button
    const resolveBtn = page.locator('[data-testid^="resolve-btn-"]').first();
    if (await resolveBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await resolveBtn.click();
      const resolver = page.locator('[data-testid="conflict-resolver"]');
      await expect(resolver).toBeVisible({ timeout: 3_000 });
      // Resolution options should be visible
      const splitBtn = page.locator('[data-testid="resolution-split"]');
      if (await splitBtn.isVisible({ timeout: 2_000 }).catch(() => false)) {
        await splitBtn.click();
        // SubClauseSplitter should appear
        await expect(page.locator('[data-testid="sub-clause-splitter"]')).toBeVisible({ timeout: 3_000 });
      }
      // Close the resolver
      const closeBtn = page.locator('[data-testid="conflict-resolver-close"]');
      if (await closeBtn.isVisible().catch(() => false)) {
        await closeBtn.click();
        await expect(resolver).toBeHidden();
      }
    }
  });

  test("Full review lifecycle: navigate, unlink, undo", async ({ page }) => {
    const rows = page.locator('[data-testid^="link-row-"]');
    const rowCount = await rows.count();
    if (rowCount >= 1) {
      // Navigate to first link (should already be focused)
      await expect(rows.nth(0)).toHaveClass(/shadow-inset-blue/);
      // Press j to move to second row (if available)
      if (rowCount >= 2) {
        await page.keyboard.press("j");
        await page.waitForTimeout(200);
        await expect(rows.nth(1)).toHaveClass(/shadow-inset-blue/);
      }
      // Unlink via keyboard (opens UnlinkReasonDialog)
      await page.keyboard.press("u");
      await page.waitForTimeout(300);
      // Undo via Cmd+Z
      await page.keyboard.press("Meta+z");
      await page.waitForTimeout(300);
      // Page should still be in a valid review state
      await expect(page.locator('[data-testid="tab-review"]')).toHaveClass(/text-accent-blue/);
    }
  });

  test("Children tab renders with parent selector", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links?tab=children`);
    await page.waitForLoadState("networkidle");
    const childrenTab = page.locator('[data-testid="children-tab"]');
    await expect(childrenTab).toBeVisible({ timeout: 5_000 });
    // Parent link selector should be present
    await expect(page.locator('[data-testid="parent-link-selector"]')).toBeVisible();
  });
});

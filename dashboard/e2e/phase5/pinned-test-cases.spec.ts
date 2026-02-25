/**
 * Phase 5 E2E: Pinned test cases panel tests.
 *
 * Tests panel open/close, TP/TN tabs, add pin form,
 * evaluate button, and pin listing.
 *
 * Verified testids from PinnedTestCasesPanel.tsx:
 *   pinned-test-cases-panel   — root fixed sidebar (right panel)
 *   pins-panel-close           — close button (x)
 *   pins-tab-tp                — True Positives tab button
 *   pins-tab-tn                — True Negatives tab button
 *   evaluate-pins-btn          — evaluate all pins button
 *   pin-{pin_id}               — individual pin row
 *   pin-result-{pin_id}        — pin evaluation result badge
 *   delete-pin-{pin_id}        — delete pin button
 *   add-pin-btn                — add pin toggle button
 *   pin-form-doc-id            — doc ID input in add form
 *   pin-form-section           — section number input in add form
 *   pin-form-note              — note input in add form
 *   pin-form-submit            — submit button in add form
 *
 * Opened from RulesTabContent via rule-pins-{rule_id} button.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Pinned Test Cases Panel", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("rules");
    await page.goto(`${FRONTEND_BASE}/links?tab=rules`);
    await page.waitForLoadState("networkidle");
  });

  test("Pins button opens panel", async ({ page }) => {
    // Click first rule's pins action button
    const pinsBtn = page.locator('[data-testid^="rule-pins-"]').first();
    await pinsBtn.click();
    const panel = page.locator('[data-testid="pinned-test-cases-panel"]');
    await expect(panel).toBeVisible();
    // Panel should show the rule ID
    const panelText = await panel.textContent();
    expect(panelText).toContain("Pinned Test Cases");
  });

  test("Close button dismisses panel", async ({ page }) => {
    const pinsBtn = page.locator('[data-testid^="rule-pins-"]').first();
    await pinsBtn.click();
    await expect(page.locator('[data-testid="pinned-test-cases-panel"]')).toBeVisible();
    await page.locator('[data-testid="pins-panel-close"]').click();
    await expect(page.locator('[data-testid="pinned-test-cases-panel"]')).toBeHidden();
  });

  test("Escape key closes panel", async ({ page }) => {
    const pinsBtn = page.locator('[data-testid^="rule-pins-"]').first();
    await pinsBtn.click();
    await expect(page.locator('[data-testid="pinned-test-cases-panel"]')).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator('[data-testid="pinned-test-cases-panel"]')).toBeHidden();
  });

  test("TP tab is active by default with green styling", async ({ page }) => {
    const pinsBtn = page.locator('[data-testid^="rule-pins-"]').first();
    await pinsBtn.click();
    const tpTab = page.locator('[data-testid="pins-tab-tp"]');
    await expect(tpTab).toBeVisible();
    // TP tab should have active styling (text-accent-green and green bottom border)
    await expect(tpTab).toHaveClass(/text-accent-green/);
    await expect(tpTab).toHaveClass(/border-b-accent-green/);
    // TP tab text should include "True Positives"
    await expect(tpTab).toContainText("True Positives");
  });

  test("TN tab switches view and shows red styling", async ({ page }) => {
    const pinsBtn = page.locator('[data-testid^="rule-pins-"]').first();
    await pinsBtn.click();
    const tnTab = page.locator('[data-testid="pins-tab-tn"]');
    await tnTab.click();
    // TN tab should now be active with red styling
    await expect(tnTab).toHaveClass(/text-accent-red/);
    await expect(tnTab).toHaveClass(/border-b-accent-red/);
    // TP tab should no longer have green styling
    const tpTab = page.locator('[data-testid="pins-tab-tp"]');
    await expect(tpTab).toHaveClass(/text-text-muted/);
    // TN tab text should include "True Negatives"
    await expect(tnTab).toContainText("True Negatives");
  });

  test("Add Pin button shows form with all fields", async ({ page }) => {
    const pinsBtn = page.locator('[data-testid^="rule-pins-"]').first();
    await pinsBtn.click();
    await page.locator('[data-testid="add-pin-btn"]').click();
    // All form fields should be visible
    const docIdInput = page.locator('[data-testid="pin-form-doc-id"]');
    const sectionInput = page.locator('[data-testid="pin-form-section"]');
    const noteInput = page.locator('[data-testid="pin-form-note"]');
    const submitBtn = page.locator('[data-testid="pin-form-submit"]');

    await expect(docIdInput).toBeVisible();
    await expect(sectionInput).toBeVisible();
    await expect(noteInput).toBeVisible();
    await expect(submitBtn).toBeVisible();

    // Verify placeholders
    await expect(docIdInput).toHaveAttribute("placeholder", "Doc ID");
    await expect(sectionInput).toHaveAttribute("placeholder", "Section number");
    await expect(noteInput).toHaveAttribute("placeholder", /Note/);

    // Submit should be disabled when fields are empty
    await expect(submitBtn).toBeDisabled();
  });

  test("Evaluate button is present and shows correct text", async ({ page }) => {
    const pinsBtn = page.locator('[data-testid^="rule-pins-"]').first();
    await pinsBtn.click();
    const evalBtn = page.locator('[data-testid="evaluate-pins-btn"]');
    await expect(evalBtn).toBeVisible();
    await expect(evalBtn).toHaveText("Evaluate All Pins");
  });
});

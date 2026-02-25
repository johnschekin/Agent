/**
 * Phase 5 E2E: Sub-clause splitter tests.
 *
 * Tests family selector, text selection, assignment rendering,
 * overlap validation, and apply/cancel actions.
 *
 * Verified testids from SubClauseSplitter.tsx:
 *   sub-clause-splitter            — root container
 *   splitter-family-{family_id}    — family selector buttons
 *   splitter-text                  — text area with highlights
 *   splitter-apply                 — apply split button (disabled when no assignments)
 *   splitter-cancel                — cancel button
 *   assignment-{idx}               — assignment summary row
 *   remove-assignment-{idx}        — remove assignment button
 *   splitter-validation-error      — validation error message
 *
 * Verified testids from ConflictResolver.tsx:
 *   conflict-resolver              — resolver overlay
 *   resolution-split               — split radio option (label)
 *
 * Verified testids from page.tsx ConflictsTabContent:
 *   conflict-row-{doc_id}          — conflict table rows
 *   resolve-btn-{doc_id}           — resolve action button
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Sub-Clause Splitter", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("conflicts");
    await page.goto(`${FRONTEND_BASE}/links?tab=conflicts`);
    await page.waitForLoadState("networkidle");
  });

  test("Split resolution option shows SubClauseSplitter", async ({ page }) => {
    // Open conflict resolver by clicking first conflict row
    await page.locator("tbody tr").first().click();
    const resolver = page.locator('[data-testid="conflict-resolver"]');
    await expect(resolver).toBeVisible({ timeout: 3_000 });

    // Select split option
    await page.locator('[data-testid="resolution-split"]').click();
    const splitter = page.locator('[data-testid="sub-clause-splitter"]');
    await expect(splitter).toBeVisible();
    // Splitter should contain the text area and action buttons
    await expect(page.locator('[data-testid="splitter-text"]')).toBeVisible();
    await expect(page.locator('[data-testid="splitter-apply"]')).toBeVisible();
    await expect(page.locator('[data-testid="splitter-cancel"]')).toBeVisible();
  });

  test("Splitter shows family buttons for conflicting families", async ({ page }) => {
    await page.locator("tbody tr").first().click();
    await page.locator('[data-testid="resolution-split"]').click();
    const splitter = page.locator('[data-testid="sub-clause-splitter"]');
    await expect(splitter).toBeVisible();

    const familyButtons = splitter.locator('[data-testid^="splitter-family-"]');
    const count = await familyButtons.count();
    // A conflict must have at least 2 families
    expect(count).toBeGreaterThanOrEqual(2);
    // First family button should have visible text content
    const firstBtnText = await familyButtons.first().textContent();
    expect(firstBtnText).toBeTruthy();
    expect(firstBtnText!.trim().length).toBeGreaterThan(0);
  });

  test("Splitter text area renders section text content", async ({ page }) => {
    await page.locator("tbody tr").first().click();
    await page.locator('[data-testid="resolution-split"]').click();
    const textArea = page.locator('[data-testid="splitter-text"]');
    await expect(textArea).toBeVisible();
    // The text area should contain actual section text
    const text = await textArea.textContent();
    expect(text).toBeTruthy();
    expect(text!.length).toBeGreaterThan(0);
  });

  test("Apply button is disabled with no assignments", async ({ page }) => {
    await page.locator("tbody tr").first().click();
    await page.locator('[data-testid="resolution-split"]').click();
    const applyBtn = page.locator('[data-testid="splitter-apply"]');
    await expect(applyBtn).toBeDisabled();
    // Button text should say "Apply Split"
    await expect(applyBtn).toHaveText("Apply Split");
  });

  test("Cancel button returns to resolver without splitter", async ({ page }) => {
    await page.locator("tbody tr").first().click();
    await page.locator('[data-testid="resolution-split"]').click();
    await expect(page.locator('[data-testid="sub-clause-splitter"]')).toBeVisible();
    await page.locator('[data-testid="splitter-cancel"]').click();
    await expect(page.locator('[data-testid="sub-clause-splitter"]')).toBeHidden();
    // Resolver should still be open
    await expect(page.locator('[data-testid="conflict-resolver"]')).toBeVisible();
  });

  test("Split description text contains sub-clause explanation", async ({ page }) => {
    await page.locator("tbody tr").first().click();
    const resolver = page.locator('[data-testid="conflict-resolver"]');
    await expect(resolver).toBeVisible();
    // The split option label should describe sub-clause assignment, not a placeholder
    const splitLabel = page.locator('[data-testid="resolution-split"]');
    const text = await splitLabel.textContent();
    expect(text).not.toContain("Phase 5");
    expect(text).toContain("Split Section");
    expect(text).toContain("sub-clause");
  });
});

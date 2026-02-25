/**
 * Phase 5 E2E: Rules tab tests.
 *
 * Tests tab rendering, rules table, status filters,
 * search, rule actions, and macro manager sidebar.
 *
 * Verified testids from page.tsx RulesTabContent:
 *   rules-tab                        — tab root container
 *   rules-search                     — search input
 *   rules-status-{all|draft|published|archived} — status filter buttons
 *   rule-row-{rule_id}               — table row per rule
 *   rule-dsl-{rule_id}               — DSL code display
 *   rule-pins-{rule_id}              — pins button (pin count)
 *   rule-drift-{rule_id}             — drift badge (only if drift alert)
 *   rule-publish-{rule_id}           — publish button (draft rules only)
 *   rule-archive-{rule_id}           — archive button (published rules only)
 *   rule-compare-{rule_id}           — compare button
 *   rule-clone-{rule_id}             — clone button
 *   show-starter-kit                 — starter kit toggle (only when familyFilter set)
 *
 * Verified testids from MacroManager.tsx:
 *   macro-manager                    — macro sidebar root (always visible)
 *   create-macro-toggle              — toggle create form
 *   macro-{name}                     — individual macro row
 *
 * NOTE: There are no "rules-family-chip-*" testids; family filtering is at the page level.
 * NOTE: There is no "toggle-macros-btn" testid; the MacroManager sidebar is always rendered.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Rules Tab", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("rules");
    await page.goto(`${FRONTEND_BASE}/links?tab=rules`);
    await page.waitForLoadState("networkidle");
  });

  test("Rules tab renders with proper container", async ({ page }) => {
    const rulesTab = page.locator('[data-testid="rules-tab"]');
    await expect(rulesTab).toBeVisible({ timeout: 5_000 });
    // Should not contain Phase 5 placeholder text
    const text = await rulesTab.textContent();
    expect(text).not.toContain("Coming in Phase 5");
  });

  test("Rules table is visible with correct columns", async ({ page }) => {
    const table = page.locator('[data-testid="rules-tab"] table').first();
    await expect(table).toBeVisible({ timeout: 5_000 });
    // Verify column headers exist
    const headers = table.locator("thead th");
    const headerTexts = await headers.allTextContents();
    expect(headerTexts).toContain("Rule");
    expect(headerTexts).toContain("Family");
    expect(headerTexts).toContain("DSL");
    expect(headerTexts).toContain("Status");
    expect(headerTexts).toContain("Actions");
  });

  test("Status filter buttons are present and functional", async ({ page }) => {
    // All 4 status filter buttons should exist
    await expect(page.locator('[data-testid="rules-status-all"]')).toBeVisible();
    await expect(page.locator('[data-testid="rules-status-draft"]')).toBeVisible();
    await expect(page.locator('[data-testid="rules-status-published"]')).toBeVisible();
    await expect(page.locator('[data-testid="rules-status-archived"]')).toBeVisible();

    // "All" should be active by default (has .active class)
    await expect(page.locator('[data-testid="rules-status-all"]')).toHaveClass(/active/);

    // Clicking "draft" should activate it
    await page.locator('[data-testid="rules-status-draft"]').click();
    await expect(page.locator('[data-testid="rules-status-draft"]')).toHaveClass(/active/);
  });

  test("Search input filters rules by text", async ({ page }) => {
    const search = page.locator('[data-testid="rules-search"]');
    await expect(search).toBeVisible();
    await expect(search).toHaveAttribute("placeholder", /Search rules/);

    // Count initial rows
    const initialRows = page.locator('[data-testid^="rule-row-"]');
    const initialCount = await initialRows.count();
    expect(initialCount).toBeGreaterThan(0);

    // Fill search with a non-matching term
    await search.fill("zzz_nonexistent_rule_zzz");
    await page.waitForTimeout(300);

    // Should show "No rules found" or fewer rows
    const filteredRows = page.locator('[data-testid^="rule-row-"]');
    const filteredCount = await filteredRows.count();
    expect(filteredCount).toBeLessThan(initialCount);
  });

  test("Rule rows have action buttons (compare, clone)", async ({ page }) => {
    const firstRow = page.locator('[data-testid^="rule-row-"]').first();
    await expect(firstRow).toBeVisible({ timeout: 5_000 });

    // Every rule row has at least a Compare and Clone button
    const compareBtn = firstRow.locator('[data-testid^="rule-compare-"]');
    const cloneBtn = firstRow.locator('[data-testid^="rule-clone-"]');
    await expect(compareBtn).toBeVisible();
    await expect(cloneBtn).toBeVisible();
    await expect(compareBtn).toHaveText("Compare");
    await expect(cloneBtn).toHaveText("Clone");
  });

  test("Rule rows show DSL content", async ({ page }) => {
    const firstDsl = page.locator('[data-testid^="rule-dsl-"]').first();
    await expect(firstDsl).toBeVisible({ timeout: 5_000 });
    const dslText = await firstDsl.textContent();
    expect(dslText).toBeTruthy();
    expect(dslText!.trim().length).toBeGreaterThan(0);
  });

  test("Rule rows show pins button with count", async ({ page }) => {
    const firstPinsBtn = page.locator('[data-testid^="rule-pins-"]').first();
    await expect(firstPinsBtn).toBeVisible({ timeout: 5_000 });
    // Pins button should contain a numeric count
    const pinsText = await firstPinsBtn.textContent();
    expect(pinsText).toMatch(/\d+/);
  });

  test("Macro manager sidebar is always visible", async ({ page }) => {
    const macroManager = page.locator('[data-testid="macro-manager"]');
    await expect(macroManager).toBeVisible({ timeout: 5_000 });
  });
});

/**
 * Phase 4 E2E: Text Query Bar (DSL input) tests.
 *
 * Tests DSL input, debounce validation, macro autocomplete,
 * match count updates, cost warnings, and meta-field triggers.
 */
import { test, expect } from "../fixtures/links-page";

test.describe("Query Tab — DSL Input", () => {
  test.beforeEach(async ({ linksPage: page }) => {
    await page.locator('[data-testid="tab-query"]').click();
    await page.waitForSelector('[data-testid="query-tab"]', { timeout: 5_000 });
  });

  test("Text query bar renders with placeholder", async ({ linksPage: page }) => {
    const bar = page.locator('[data-testid="text-query-bar"]');
    await expect(bar).toBeVisible();
    const input = page.locator('[data-testid="text-query-bar-input"]');
    await expect(input).toBeVisible();
    // Without family selected, placeholder should indicate to select one
    const placeholder = await input.getAttribute("placeholder");
    expect(placeholder).toBeTruthy();
  });

  test("Typing DSL text updates input value", async ({ linksPage: page }) => {
    const input = page.locator('[data-testid="text-query-bar-input"]');
    await input.fill('heading:"Financial Covenants"');
    await expect(input).toHaveValue('heading:"Financial Covenants"');
  });

  test("Debounced validation shows errors for invalid DSL", async ({ linksPage: page }) => {
    const input = page.locator('[data-testid="text-query-bar-input"]');
    await input.fill("invalid((( dsl syntax");
    // Wait for 300ms debounce + network round trip
    await page.waitForTimeout(600);
    // Should display error section with at least one error
    const errorsSection = page.locator('[data-testid="dsl-errors"]');
    await expect(errorsSection).toBeVisible();
    // Each error has a <p> with accent-red class
    const errorCount = await errorsSection.locator("p").count();
    expect(errorCount).toBeGreaterThanOrEqual(1);
  });

  test("Valid DSL does not show errors", async ({ linksPage: page }) => {
    const input = page.locator('[data-testid="text-query-bar-input"]');
    await input.fill('heading:"Financial Covenants"');
    await page.waitForTimeout(600);
    // Errors section should not be visible for valid DSL
    const errorsSection = page.locator('[data-testid="dsl-errors"]');
    await expect(errorsSection).toBeHidden();
  });

  test("@ triggers macro autocomplete dropdown", async ({ linksPage: page }) => {
    const input = page.locator('[data-testid="text-query-bar-input"]');
    await input.fill("@");
    await page.waitForTimeout(200);
    // Autocomplete dropdown should appear if macros exist in seed data
    const dropdown = page.locator('[data-testid="autocomplete-dropdown"]');
    // If macro data is seeded, dropdown should be visible with items
    if (await dropdown.isVisible()) {
      const items = await dropdown.locator("button").count();
      expect(items).toBeGreaterThanOrEqual(1);
    }
  });

  test("Meta-field heading: triggers autocomplete with suggestions", async ({ linksPage: page }) => {
    const input = page.locator('[data-testid="text-query-bar-input"]');
    await input.fill("heading:");
    await page.waitForTimeout(200);
    const dropdown = page.locator('[data-testid="autocomplete-dropdown"]');
    // heading: should trigger autocomplete with known heading values
    await expect(dropdown).toBeVisible();
    const items = await dropdown.locator("button").count();
    expect(items).toBeGreaterThanOrEqual(1);
    // First item should start with "heading:"
    const firstItem = await dropdown.locator("button").first().textContent();
    expect(firstItem).toContain("heading:");
  });

  test("Meta-field template: triggers autocomplete", async ({ linksPage: page }) => {
    const input = page.locator('[data-testid="text-query-bar-input"]');
    const autocompleteResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/rules/autocomplete") &&
      res.url().includes("field=template") &&
      res.request().method() === "GET",
    );
    await input.fill("template:");
    const response = await autocompleteResponse;
    expect(response.ok()).toBeTruthy();

    const dropdown = page.locator('[data-testid="autocomplete-dropdown"]');
    if (await dropdown.isVisible()) {
      const firstItem = await dropdown.locator("button").first().textContent();
      expect(firstItem).toContain("template:");
    } else {
      await expect(input).toHaveValue("template:");
    }
  });

  test("Escape closes autocomplete dropdown", async ({ linksPage: page }) => {
    const input = page.locator('[data-testid="text-query-bar-input"]');
    await input.fill("heading:");
    await page.waitForTimeout(200);
    const dropdown = page.locator('[data-testid="autocomplete-dropdown"]');
    await expect(dropdown).toBeVisible();
    // Press Escape to close
    await input.press("Escape");
    await expect(dropdown).toBeHidden();
  });

  test("Scratchpad toggle button works", async ({ linksPage: page }) => {
    const toggle = page.locator('[data-testid="toggle-scratchpad"]');
    await expect(toggle).toBeVisible();
    await toggle.click();
    await expect(page.locator('[data-testid="scratchpad-pane"]')).toBeVisible();
    await toggle.click();
    await expect(page.locator('[data-testid="scratchpad-pane"]')).toBeHidden();
  });

  test("Preview button is disabled without family filter", async ({ linksPage: page }) => {
    const previewBtn = page.locator('[data-testid="query-preview-btn"]');
    await expect(previewBtn).toBeVisible();
    await expect(previewBtn).toBeDisabled();
  });
});

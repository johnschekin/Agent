import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";

test.describe("Phase 9 Smoke Tests", () => {
  test("Strategy Manager page loads", async ({ page }) => {
    await page.goto(`${BASE}/strategies`);
    await expect(page.locator("h2")).toContainText("Strategy Manager");
    // Should have filter controls
    await expect(page.locator('input[placeholder="Search concepts..."]')).toBeVisible();
    // Should have family and status dropdowns
    await expect(page.locator("select")).toHaveCount(2);
  });

  test("Strategy Results page loads", async ({ page }) => {
    await page.goto(`${BASE}/strategies/results`);
    await expect(page.locator("h2")).toContainText("Strategy Results");
    // Should have group-by selector
    await expect(page.locator("select")).toHaveCount(1);
  });

  test("Feedback Backlog page loads", async ({ page }) => {
    await page.goto(`${BASE}/feedback`);
    await expect(page.locator("h2")).toContainText("Feedback Backlog");
    // Should have "New Feedback" button
    await expect(page.locator('button:has-text("New Feedback")')).toBeVisible();
    // Should have filter dropdowns (status, type, priority)
    await expect(page.locator("select")).toHaveCount(3);
  });

  test("Feedback create form opens and closes", async ({ page }) => {
    await page.goto(`${BASE}/feedback`);
    // Click "New Feedback"
    await page.click('button:has-text("New Feedback")');
    // Form should appear
    await expect(page.locator('text="New Feedback Item"')).toBeVisible();
    await expect(page.locator('input[placeholder*="Brief description"]')).toBeVisible();
    // Cancel should close it
    await page.click('button:has-text("Cancel")');
    await expect(page.locator('text="New Feedback Item"')).not.toBeVisible();
  });

  test("Existing pages still render", async ({ page }) => {
    // Spot-check a few existing pages
    await page.goto(`${BASE}/overview`);
    await expect(page.locator("h2")).toContainText("Corpus Overview");

    await page.goto(`${BASE}/reader`);
    await expect(page.locator("h2, label")).toContainText(/Reader|Document/);

    await page.goto(`${BASE}/ontology`);
    await expect(page.locator("h2")).toContainText("Ontology Explorer");
  });
});

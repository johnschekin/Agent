/**
 * Ontology Notes Persistence Tests
 *
 * Tests that notes typed into the ontology node detail panel persist
 * after navigating away and returning (both within session and after reload).
 *
 * Usage: npx playwright test tests/ontology-notes.spec.ts
 * Requires: @playwright/test, dashboard frontend (localhost:3000), API server (localhost:8000)
 */
import { test, expect } from "@playwright/test";

const BASE = "http://localhost:3000";

test.describe("Ontology Notes Persistence", () => {
  const uniqueNote = `PW-test-note-${Date.now()}`;

  test("save note, navigate away, return — note persists", async ({ page }) => {
    await page.goto(`${BASE}/ontology`, { waitUntil: "networkidle" });
    await expect(page.locator("h2")).toContainText("Ontology Explorer");

    const tree = page.locator('[role="tree"]');
    await expect(tree).toBeVisible({ timeout: 15000 });

    const treeItems = page.locator('[role="treeitem"]');
    await expect(treeItems.first()).toBeVisible({ timeout: 10000 });

    const firstFamily = treeItems.nth(1);
    await firstFamily.click();

    const textarea = page.locator('[data-testid="notes-textarea"]');
    await expect(textarea).toBeVisible({ timeout: 10000 });
    await textarea.clear();
    await textarea.fill(uniqueNote);

    const saveBtn = page.locator('[data-testid="notes-save-btn"]');
    await expect(saveBtn).toBeEnabled();
    await saveBtn.click();

    await expect(page.locator('[data-testid="notes-saved"]')).toBeVisible({ timeout: 10000 });
    await expect(saveBtn).toBeDisabled();

    const otherNode = treeItems.nth(2);
    await otherNode.click();
    await expect(textarea).toBeVisible({ timeout: 10000 });
    await page.waitForTimeout(500);

    await firstFamily.click();
    await expect(textarea).toHaveValue(uniqueNote, { timeout: 10000 });
  });

  test("save note persists across full page reload", async ({ page }) => {
    const reloadNote = `PW-reload-${Date.now()}`;

    await page.goto(`${BASE}/ontology`, { waitUntil: "networkidle" });
    const treeItems = page.locator('[role="treeitem"]');
    await expect(treeItems.first()).toBeVisible({ timeout: 15000 });

    const targetNode = treeItems.nth(1);
    await targetNode.click();

    const textarea = page.locator('[data-testid="notes-textarea"]');
    await expect(textarea).toBeVisible({ timeout: 10000 });
    await textarea.clear();
    await textarea.fill(reloadNote);

    const saveBtn = page.locator('[data-testid="notes-save-btn"]');
    await saveBtn.click();
    await expect(page.locator('[data-testid="notes-saved"]')).toBeVisible({ timeout: 10000 });

    await page.reload({ waitUntil: "networkidle" });

    await expect(page.locator('[role="tree"]')).toBeVisible({ timeout: 15000 });
    const reloadedItems = page.locator('[role="treeitem"]');
    await expect(reloadedItems.first()).toBeVisible({ timeout: 10000 });
    await reloadedItems.nth(1).click();

    const reloadedTextarea = page.locator('[data-testid="notes-textarea"]');
    await expect(reloadedTextarea).toHaveValue(reloadNote, { timeout: 10000 });
  });
});

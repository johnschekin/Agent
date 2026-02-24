/**
 * Ontology Notes Persistence Tests
 *
 * Tests that notes typed into the ontology node detail panel persist
 * after navigating away and returning (both within-session and after reload).
 *
 * Usage: node tests/ontology-notes-smoke.js
 * Requires: dashboard frontend (localhost:3000), API server (localhost:8000)
 */
const { chromium } = require("playwright");

const BASE = "http://localhost:3000";
const TIMEOUT = 15000;

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  let passed = 0;
  let failed = 0;

  async function check(name, fn) {
    const page = await context.newPage();
    try {
      await fn(page);
      console.log(`  ✓ ${name}`);
      passed++;
    } catch (err) {
      console.log(`  ✗ ${name}`);
      console.log(`    ${err.message.split("\n")[0]}`);
      failed++;
    } finally {
      await page.close();
    }
  }

  async function expectVisible(page, selector) {
    await page.waitForSelector(selector, { timeout: TIMEOUT, state: "visible" });
  }

  console.log("\nOntology Notes Persistence Tests\n");

  // ---------------------------------------------------------------------------
  // Test 1: Save note, navigate away, return — note persists
  // ---------------------------------------------------------------------------
  await check("Note persists after navigating away and returning", async (page) => {
    const uniqueNote = `PW-nav-${Date.now()}`;

    // 1. Load ontology page and wait for tree
    await page.goto(`${BASE}/ontology`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectVisible(page, '[role="tree"]');
    await expectVisible(page, '[role="treeitem"]');

    // 2. Click the second tree item (first family under first domain)
    const treeItems = page.locator('[role="treeitem"]');
    const firstFamily = treeItems.nth(1);
    const firstFamilyLabel = await firstFamily.textContent();
    await firstFamily.click();

    // 3. Wait for the notes textarea in the detail panel
    await expectVisible(page, '[data-testid="notes-textarea"]');
    const textarea = page.locator('[data-testid="notes-textarea"]');

    // 4. Clear and type the unique note
    await textarea.click();
    await textarea.fill("");
    await textarea.fill(uniqueNote);

    // 5. Save button should be enabled; click it
    const saveBtn = page.locator('[data-testid="notes-save-btn"]');
    const isDisabled = await saveBtn.isDisabled();
    if (isDisabled) {
      throw new Error("Save button should be enabled after typing a note");
    }
    await saveBtn.click();

    // 6. Wait for "Saved" indicator
    await expectVisible(page, '[data-testid="notes-saved"]');

    // Verify save button is now disabled
    const isDisabledAfterSave = await saveBtn.isDisabled();
    if (!isDisabledAfterSave) {
      throw new Error("Save button should be disabled after successful save");
    }

    // 7. Navigate to a different node
    const otherNode = treeItems.nth(2);
    await otherNode.click();
    // Give the UI time to update
    await page.waitForTimeout(1000);

    // Verify the textarea no longer contains our note (different node)
    const otherVal = await textarea.inputValue();
    if (otherVal === uniqueNote) {
      throw new Error("After navigating to a different node, textarea should not still show the original note");
    }

    // 8. Navigate back to the original node
    await firstFamily.click();
    // Wait for the detail panel data to load
    await page.waitForTimeout(1000);

    // 9. Verify the note persists
    const restoredVal = await textarea.inputValue();
    if (restoredVal !== uniqueNote) {
      throw new Error(
        `Expected textarea to contain "${uniqueNote}" but got "${restoredVal}" (node: ${firstFamilyLabel?.trim()})`
      );
    }
  });

  // ---------------------------------------------------------------------------
  // Test 2: Save note, full page reload — note persists
  // ---------------------------------------------------------------------------
  await check("Note persists across full page reload", async (page) => {
    const reloadNote = `PW-reload-${Date.now()}`;

    // 1. Load ontology page
    await page.goto(`${BASE}/ontology`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectVisible(page, '[role="tree"]');
    await expectVisible(page, '[role="treeitem"]');

    // 2. Click a tree node (second item = first family)
    const treeItems = page.locator('[role="treeitem"]');
    await treeItems.nth(1).click();

    // 3. Type and save
    await expectVisible(page, '[data-testid="notes-textarea"]');
    const textarea = page.locator('[data-testid="notes-textarea"]');
    await textarea.click();
    await textarea.fill("");
    await textarea.fill(reloadNote);

    const saveBtn = page.locator('[data-testid="notes-save-btn"]');
    await saveBtn.click();
    await expectVisible(page, '[data-testid="notes-saved"]');

    // 4. Full page reload
    await page.reload({ waitUntil: "networkidle", timeout: TIMEOUT });

    // 5. Re-select the same node
    await expectVisible(page, '[role="tree"]');
    await expectVisible(page, '[role="treeitem"]');
    const reloadedItems = page.locator('[role="treeitem"]');
    await reloadedItems.nth(1).click();

    // 6. Verify note persists
    await expectVisible(page, '[data-testid="notes-textarea"]');
    const reloadedTextarea = page.locator('[data-testid="notes-textarea"]');
    // Wait a moment for query to resolve
    await page.waitForTimeout(1000);

    const val = await reloadedTextarea.inputValue();
    if (val !== reloadNote) {
      throw new Error(`Expected "${reloadNote}" after reload, got "${val}"`);
    }
  });

  // ---------------------------------------------------------------------------
  // Test 3: Save button is disabled when no changes
  // ---------------------------------------------------------------------------
  await check("Save button disabled when notes unchanged", async (page) => {
    await page.goto(`${BASE}/ontology`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectVisible(page, '[role="treeitem"]');

    const treeItems = page.locator('[role="treeitem"]');
    await treeItems.nth(1).click();
    await expectVisible(page, '[data-testid="notes-textarea"]');

    // Save button should be disabled when notes match loaded data
    const saveBtn = page.locator('[data-testid="notes-save-btn"]');
    // Wait for data to load
    await page.waitForTimeout(500);
    const isDisabled = await saveBtn.isDisabled();
    if (!isDisabled) {
      throw new Error("Save button should be disabled when notes are unchanged from loaded data");
    }
  });

  console.log(`\nResult: ${passed} passed, ${failed} failed\n`);

  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});

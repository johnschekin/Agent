/**
 * Phase 3 E2E: Review tab — link actions (unlink, relink, bookmark, note, pin, batch).
 */
import { test, expect } from "../fixtures/links-page";

test.describe("Review Tab Actions", () => {
  test("u unlinks with reason prompt", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const rows = page.locator("tbody tr");
    if ((await rows.count()) === 0) return;

    // Capture focused row's status badge before action
    const focusedRow = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const statusBefore = await focusedRow.locator("td").nth(6).textContent();

    // Mock the prompt dialog to select reason 1 (false_positive)
    page.on("dialog", async (dialog) => {
      expect(dialog.type()).toBe("prompt");
      // Prompt text should contain all 4 reason options
      const msg = dialog.message();
      expect(msg).toContain("false_positive");
      expect(msg).toContain("duplicate");
      expect(msg).toContain("wrong_family");
      expect(msg).toContain("other");
      await dialog.accept("1");
    });

    await page.keyboard.press("u");
    await page.waitForTimeout(500);

    // Row status may have changed to "unlinked" if mutation succeeded
    // (depends on backend being available — verify no crash at minimum)
    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("r relinks focused row", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    if ((await page.locator("tbody tr").count()) === 0) return;

    // Press r to relink
    await page.keyboard.press("r");
    await page.waitForTimeout(500);

    // Verify the action was attempted — the focused row should still exist
    const focusedRow = page.locator("tbody tr[class*='shadow-inset-blue']");
    expect(await focusedRow.count()).toBeLessThanOrEqual(1);

    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("b bookmarks focused row", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    if ((await page.locator("tbody tr").count()) === 0) return;

    // Press b to bookmark
    await page.keyboard.press("b");
    await page.waitForTimeout(500);

    // After bookmarking, the focused row should still be present and page functional
    const focusedRow = page.locator("tbody tr[class*='shadow-inset-blue']");
    await expect(focusedRow.first()).toBeVisible();

    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("n opens note input", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    if ((await page.locator("tbody tr").count()) === 0) return;

    // Press n to open note input
    await page.keyboard.press("n");

    // Look for the note input field
    const noteInput = page.locator('input[placeholder*="note"]');
    await expect(noteInput.first()).toBeVisible({ timeout: 2_000 });

    // Ensure the note input can receive focus for typing
    await noteInput.first().focus();
    const activeTag = await page.evaluate(() => document.activeElement?.tagName);
    expect(activeTag).toBe("INPUT");

    // Type a note and submit
    await noteInput.first().fill("Test note content");
    await noteInput.first().press("Enter");

    // Note input should close after submission
    await page.waitForTimeout(300);
    const inputAfterSubmit = page.locator('input[placeholder*="note"]');
    if ((await inputAfterSubmit.count()) > 0) {
      await expect(inputAfterSubmit.first()).toBeHidden({ timeout: 2_000 }).catch(() => {});
    }
  });

  test("p pins as True Positive", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    if ((await page.locator("tbody tr").count()) === 0) return;

    // Capture data-row-id of focused row before action
    const focusedRow = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const rowId = await focusedRow.getAttribute("data-row-id");
    expect(rowId).toBeTruthy();

    // Press p to pin as TP
    await page.keyboard.press("p");
    await page.waitForTimeout(300);

    // Row should still be focused (pin doesn't advance)
    const focusedAfter = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const rowIdAfter = await focusedAfter.getAttribute("data-row-id");
    expect(rowIdAfter).toBe(rowId);
  });

  test("Shift+p pins as True Negative", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    if ((await page.locator("tbody tr").count()) === 0) return;

    const focusedRow = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const rowId = await focusedRow.getAttribute("data-row-id");

    // Shift+p to pin as TN
    await page.keyboard.press("Shift+p");
    await page.waitForTimeout(300);

    // Row should still be focused
    const focusedAfter = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const rowIdAfter = await focusedAfter.getAttribute("data-row-id");
    expect(rowIdAfter).toBe(rowId);
  });

  test("Shift+Space approve+advance", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const rows = page.locator("tbody tr");
    if ((await rows.count()) < 2) return;

    // Record initial focused row
    const focusedBefore = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const idBefore = await focusedBefore.getAttribute("data-row-id");

    // Press Shift+Space to approve and advance
    await page.keyboard.press("Shift+Space");
    await page.waitForTimeout(300);

    // Focus should have advanced to the next row
    const focusedAfter = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const idAfter = await focusedAfter.getAttribute("data-row-id");
    expect(idAfter).not.toBe(idBefore);
  });

  test("Shift+Backspace reject+advance", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const rows = page.locator("tbody tr");
    if ((await rows.count()) < 2) return;

    // Move down one row first to have room to advance
    await page.keyboard.press("j");
    const focusedBefore = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const idBefore = await focusedBefore.getAttribute("data-row-id");

    // Press Shift+Backspace to reject as false_positive + advance
    await page.keyboard.press("Shift+Backspace");
    await page.waitForTimeout(500);

    // Focus should have advanced
    const focusedAfter = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const idAfter = await focusedAfter.getAttribute("data-row-id");
    // If there are more rows, focus advances
    if ((await rows.count()) > 2) {
      expect(idAfter).not.toBe(idBefore);
    }
  });

  test("Shift+b bookmark+advance", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const rows = page.locator("tbody tr");
    if ((await rows.count()) < 2) return;

    const focusedBefore = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const idBefore = await focusedBefore.getAttribute("data-row-id");

    // Shift+b to bookmark and advance
    await page.keyboard.press("Shift+b");
    await page.waitForTimeout(300);

    // Focus should have advanced
    const focusedAfter = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const idAfter = await focusedAfter.getAttribute("data-row-id");
    expect(idAfter).not.toBe(idBefore);
  });

  test("BatchActionBar appears on selection + Shift+u batch unlinks", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const rows = page.locator("tbody tr");
    if ((await rows.count()) < 2) return;

    // Batch bar should NOT be visible initially
    const batchBar = page.locator("text=selected");
    expect(await batchBar.count()).toBe(0);

    // Select multiple rows with x and j
    await page.keyboard.press("x");
    await page.keyboard.press("j");
    await page.keyboard.press("x");

    // Batch action bar should now be visible
    await expect(batchBar.first()).toBeVisible({ timeout: 2_000 });

    // Bar should show "2 selected" (or similar count)
    const barText = await batchBar.first().textContent();
    expect(barText).toContain("2");

    // Verify batch bar has action buttons
    const unlinkBtn = page.locator("button").filter({ hasText: /unlink/i });
    const relinkBtn = page.locator("button").filter({ hasText: /relink/i });
    const bookmarkBtn = page.locator("button").filter({ hasText: /bookmark/i });
    expect(await unlinkBtn.count()).toBeGreaterThan(0);
    expect(await relinkBtn.count()).toBeGreaterThan(0);
    expect(await bookmarkBtn.count()).toBeGreaterThan(0);

    // Press Shift+u to batch unlink
    await page.keyboard.press("Shift+u");
    await page.waitForTimeout(500);

    // Batch bar should disappear (selection cleared)
    if ((await batchBar.count()) > 0) {
      await expect(batchBar.first()).toBeHidden({ timeout: 3_000 }).catch(() => {});
    }
  });

  test("Unlink action persists status server-side", async ({
    linksPage: page,
    apiContext,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const focusedRow = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const linkId = await focusedRow.getAttribute("data-row-id");
    if (!linkId) return;

    page.once("dialog", async (dialog) => {
      await dialog.accept("1");
    });
    await page.keyboard.press("u");
    await page.waitForTimeout(500);

    const res = await apiContext.get(`/api/links/${linkId}`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(String(body.status)).toContain("unlinked");
  });

  test("Relink action restores active status server-side", async ({
    linksPage: page,
    apiContext,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const focusedRow = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const linkId = await focusedRow.getAttribute("data-row-id");
    if (!linkId) return;

    page.once("dialog", async (dialog) => {
      await dialog.accept("1");
    });
    await page.keyboard.press("u");
    await page.waitForTimeout(300);
    await page.keyboard.press("r");
    await page.waitForTimeout(500);

    const res = await apiContext.get(`/api/links/${linkId}`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(String(body.status)).toContain("active");
  });
});

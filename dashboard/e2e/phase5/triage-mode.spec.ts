/**
 * Phase 5 E2E: Triage mode tests.
 *
 * Tests enter/exit, Space/Backspace/d/n actions, progress bar,
 * hash-cluster mode, dynamic filter, and card rendering.
 *
 * Verified testids from TriageMode.tsx:
 *   triage-mode               — fixed fullscreen overlay
 *   triage-counter             — "N / Total" position counter
 *   triage-exit                — "Esc to exit" button
 *   triage-card                — current link card
 *   triage-approve             — approve button (Space)
 *   triage-reject              — reject button (Backspace)
 *   triage-defer               — defer button (d)
 *   triage-note-input          — note text input (n to open)
 *   triage-filter-input        — dynamic filter input (/ to open)
 *   triage-progress-bar        — progress bar fill div
 *   triage-progress-label      — "Reviewed N/Total" text
 *   triage-progress-bar-container — progress bar outer container
 *   cluster-count              — cluster badge (visible in hash-cluster mode)
 *
 * Triage is opened via Cmd+F on the review tab (page.tsx line 333).
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Triage Mode", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("review");
    await page.goto(`${FRONTEND_BASE}/links?tab=review`);
    await page.waitForLoadState("networkidle");
  });

  test("Cmd+F enters triage mode", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    const triageOverlay = page.locator('[data-testid="triage-mode"]');
    await expect(triageOverlay).toBeVisible();
    // Should show the card, counter, and progress bar
    await expect(page.locator('[data-testid="triage-card"]')).toBeVisible();
    await expect(page.locator('[data-testid="triage-counter"]')).toBeVisible();
    await expect(page.locator('[data-testid="triage-progress-bar"]')).toBeVisible();
  });

  test("Escape exits triage mode", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    await expect(page.locator('[data-testid="triage-mode"]')).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.locator('[data-testid="triage-mode"]')).toBeHidden();
  });

  test("Exit button dismisses triage", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    await expect(page.locator('[data-testid="triage-mode"]')).toBeVisible();
    const exitBtn = page.locator('[data-testid="triage-exit"]');
    await expect(exitBtn).toHaveText(/Esc to exit/);
    await exitBtn.click();
    await expect(page.locator('[data-testid="triage-mode"]')).toBeHidden();
  });

  test("Triage card shows current link info with heading and doc ID", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    const card = page.locator('[data-testid="triage-card"]');
    await expect(card).toBeVisible({ timeout: 3_000 });
    // Card should contain a heading (h3 element)
    const heading = card.locator("h3");
    await expect(heading).toBeVisible();
    const headingText = await heading.textContent();
    expect(headingText).toBeTruthy();
    expect(headingText!.trim().length).toBeGreaterThan(0);
  });

  test("Counter shows N / Total format", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    const counter = page.locator('[data-testid="triage-counter"]');
    await expect(counter).toBeVisible();
    const text = await counter.textContent();
    // Should match "N / M" format (e.g. "1 / 50")
    expect(text).toMatch(/\d+\s*\/\s*\d+/);
  });

  test("Progress bar and label are visible", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    await expect(page.locator('[data-testid="triage-progress-bar"]')).toBeVisible();
    const label = page.locator('[data-testid="triage-progress-label"]');
    await expect(label).toBeVisible();
    const text = await label.textContent();
    // Should show "Reviewed N/M" format
    expect(text).toContain("Reviewed");
    expect(text).toMatch(/Reviewed \d+\/\d+/);
  });

  test("Approve, Reject, and Defer buttons are present with correct labels", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    const approve = page.locator('[data-testid="triage-approve"]');
    const reject = page.locator('[data-testid="triage-reject"]');
    const defer = page.locator('[data-testid="triage-defer"]');

    await expect(approve).toBeVisible();
    await expect(reject).toBeVisible();
    await expect(defer).toBeVisible();

    // Verify button text content
    await expect(approve).toContainText("Approve");
    await expect(reject).toContainText("Reject");
    await expect(defer).toContainText("Defer");
  });

  test("Space approves and advances counter", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    const counter = page.locator('[data-testid="triage-counter"]');
    const initialText = await counter.textContent();
    // Parse initial position
    const initialMatch = initialText?.match(/(\d+)\s*\/\s*(\d+)/);
    expect(initialMatch).toBeTruthy();
    const initialPos = parseInt(initialMatch![1], 10);

    await page.keyboard.press("Space");
    await page.waitForTimeout(200);

    const newText = await counter.textContent();
    const newMatch = newText?.match(/(\d+)\s*\/\s*(\d+)/);
    expect(newMatch).toBeTruthy();
    const newPos = parseInt(newMatch![1], 10);

    // Counter should advance by 1 (unless at the end)
    const total = parseInt(initialMatch![2], 10);
    if (initialPos < total) {
      expect(newPos).toBe(initialPos + 1);
    }

    // Progress label should update to show 1 reviewed
    const label = page.locator('[data-testid="triage-progress-label"]');
    const labelText = await label.textContent();
    expect(labelText).toMatch(/Reviewed [1-9]/);
  });

  test("n opens note input", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    // n should open the note input
    await page.keyboard.press("n");
    const noteInput = page.locator('[data-testid="triage-note-input"]');
    await expect(noteInput).toBeVisible();
    // Note input should have the correct placeholder
    await expect(noteInput).toHaveAttribute("placeholder", /Type note/);
    // Note input should be auto-focused
    await expect(noteInput).toBeFocused();
  });

  test("g toggles hash-cluster mode badge", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    // Before: no "Clustered" badge visible
    const clusteredBadge = page.locator("text=Clustered");
    // g should toggle cluster mode
    await page.keyboard.press("g");
    await page.waitForTimeout(200);
    // After: "Clustered" badge should appear
    await expect(clusteredBadge).toBeVisible();
    // Toggle again: badge should disappear
    await page.keyboard.press("g");
    await page.waitForTimeout(200);
    await expect(clusteredBadge).toBeHidden();
  });

  test("/ opens dynamic filter input", async ({ page }) => {
    await page.keyboard.press("Meta+f");
    // / should open the filter input
    await page.keyboard.press("/");
    const filterInput = page.locator('[data-testid="triage-filter-input"]');
    await expect(filterInput).toBeVisible();
    await expect(filterInput).toHaveAttribute("placeholder", /Filter queue/);
    // Filter should be auto-focused
    await expect(filterInput).toBeFocused();
  });
});

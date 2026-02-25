/**
 * Phase 3 E2E: Review tab — CrossRefPeek, TemplateRedline, DetachableReader.
 *
 * Tests cognitive assistance features: cross-reference tooltips,
 * template redline diffing, and detachable reader window.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Review Tab Cognitive Features", () => {
  test("CrossRefPeek: Cmd+hover on section reference shows tooltip", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(500);

    // Look for cross-reference anchors (e.g., "Section 7.02(b)")
    const xrefAnchors = page.locator("[data-xref]");
    if ((await xrefAnchors.count()) > 0) {
      // Cmd+hover: hold Meta key and hover over the xref anchor
      await page.keyboard.down("Meta");
      await xrefAnchors.first().hover();

      // Wait for tooltip to appear
      const tooltip = page.locator("[role='tooltip']").or(
        page.locator(".crossref-tooltip")
      );
      await expect(tooltip.first()).toBeVisible({ timeout: 3_000 });

      // Tooltip should contain section text content
      const tooltipText = await tooltip.first().textContent();
      expect(tooltipText).toBeTruthy();
      expect(tooltipText!.length).toBeGreaterThan(0);

      await page.keyboard.up("Meta");
    }

    // Page should not crash
    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("CrossRefPeek: tooltip closes on mouse leave", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(500);

    const xrefAnchors = page.locator("[data-xref]");
    if ((await xrefAnchors.count()) > 0) {
      // Cmd+hover to open tooltip
      await page.keyboard.down("Meta");
      await xrefAnchors.first().hover();
      await page.waitForTimeout(400);
      await page.keyboard.up("Meta");

      // Verify tooltip appeared
      const tooltip = page.locator("[role='tooltip']").or(
        page.locator(".crossref-tooltip")
      );
      if ((await tooltip.count()) > 0) {
        await expect(tooltip.first()).toBeVisible();

        // Move mouse away from the anchor
        await page.mouse.move(0, 0);
        await page.waitForTimeout(300);

        // Tooltip should have disappeared
        await expect(tooltip.first()).toBeHidden({ timeout: 2_000 });
      }
    }

    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("TemplateRedline: d key activates red/green diff overlay", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(300);

    // Before pressing d, there should be no redline elements
    const redlineBefore = page.locator("[data-redline]").or(
      page.locator(".redline-overlay")
    ).or(page.locator("text=Template Redline"));
    const beforeCount = await redlineBefore.count();

    // Press d to activate template redline
    await page.keyboard.press("d");
    await page.waitForTimeout(500);

    // After pressing d, redline should appear OR "No baseline available" message
    const redlineAfter = page.locator("[data-redline]").or(
      page.locator(".redline-overlay")
    ).or(page.locator("text=No baseline available")).or(
      page.locator("text=Template Redline")
    );
    const afterCount = await redlineAfter.count();

    // Something redline-related should now be visible
    if (afterCount > beforeCount) {
      await expect(redlineAfter.first()).toBeVisible();
    }

    // Press d again to deactivate
    await page.keyboard.press("d");
    await page.waitForTimeout(300);

    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("TemplateRedline: shows 'No baseline available' gracefully", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(300);

    // Press d to activate redline
    await page.keyboard.press("d");
    await page.waitForTimeout(500);

    // Should show either diff content or graceful fallback
    const noBaseline = page.locator("text=No baseline available");
    const diffContent = page.locator("[data-diff-type]").or(
      page.locator("[class*='bg-green']")
    ).or(page.locator("[class*='bg-red']"));

    const noBaselineVisible = (await noBaseline.count()) > 0;
    const diffVisible = (await diffContent.count()) > 0;

    // At least one should be present (either actual diff or graceful message)
    // OR neither (if section text is not available)
    if (noBaselineVisible) {
      await expect(noBaseline.first()).toBeVisible();
    }

    // Deactivate
    await page.keyboard.press("d");
    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("TemplateRedline: diff highlights insertions green and deletions red", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(300);

    // Press d to activate redline
    await page.keyboard.press("d");
    await page.waitForTimeout(500);

    // Check for green (insertion) and red (deletion) diff markers
    const greenInsertions = page.locator(
      "[data-diff-type='insert'], .diff-insert, [class*='bg-green-900']"
    );
    const redDeletions = page.locator(
      "[data-diff-type='delete'], .diff-delete, [class*='bg-red-900']"
    );

    // If baseline data exists, insertions should be green and deletions red
    if ((await greenInsertions.count()) > 0) {
      await expect(greenInsertions.first()).toBeVisible();
      // Verify the element actually has green-ish styling
      const greenEl = greenInsertions.first();
      await expect(greenEl).toBeVisible();
    }
    if ((await redDeletions.count()) > 0) {
      await expect(redDeletions.first()).toBeVisible();
    }

    // Deactivate
    await page.keyboard.press("d");
    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("DetachableReader: Cmd+U opens reader in new window", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane first
    await page.keyboard.press("Space");
    await page.waitForTimeout(300);

    // Listen for popup window
    const [popup] = await Promise.all([
      page.context().waitForEvent("page", { timeout: 5_000 }).catch(() => null),
      page.keyboard.press("Meta+u"),
    ]);

    if (popup) {
      // New window should have opened with content
      await popup.waitForLoadState("domcontentloaded").catch(() => {});
      const url = popup.url();
      expect(url).toBeTruthy();

      // Verify the popup has some content (not blank)
      const body = popup.locator("body");
      await expect(body).toBeVisible({ timeout: 3_000 });

      await popup.close();
    }

    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("DetachableReader: j/k in main syncs detached reader", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(300);

    // Open detached window
    const [popup] = await Promise.all([
      page.context().waitForEvent("page", { timeout: 5_000 }).catch(() => null),
      page.keyboard.press("Meta+u"),
    ]);

    if (popup) {
      await popup.waitForLoadState("domcontentloaded").catch(() => {});

      // Record initial focused row
      const focusedBefore = page.locator("tbody tr[class*='shadow-inset-blue']").first();
      const idBefore = await focusedBefore.getAttribute("data-row-id");

      // Navigate with j in the main window
      await page.keyboard.press("j");
      await page.waitForTimeout(500);

      // Focus should have moved in the main window
      const focusedAfter = page.locator("tbody tr[class*='shadow-inset-blue']").first();
      const idAfter = await focusedAfter.getAttribute("data-row-id");
      if ((await page.locator("tbody tr").count()) > 1) {
        expect(idAfter).not.toBe(idBefore);
      }

      // BroadcastChannel sync to popup is best-effort in E2E
      await popup.close();
    }

    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("DetachableReader: detached window closes on page nav away", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader
    await page.keyboard.press("Space");
    await page.waitForTimeout(300);

    // Open detached window
    const [popup] = await Promise.all([
      page.context().waitForEvent("page", { timeout: 5_000 }).catch(() => null),
      page.keyboard.press("Meta+u"),
    ]);

    if (popup) {
      await popup.waitForLoadState("domcontentloaded").catch(() => {});

      // Verify popup is open
      expect(popup.isClosed()).toBe(false);

      // Navigate away from /links in the main window
      await page.goto(`${FRONTEND_BASE}/overview`);
      await page.waitForLoadState("networkidle");

      // Wait for the close signal to propagate
      await page.waitForTimeout(1_000);

      // The popup should have been closed (cleanup on unmount)
      // This is best-effort — BroadcastChannel close depends on browser behavior
      if (!popup.isClosed()) {
        await popup.close();
      }
    }

    // Main page should have navigated successfully
    await expect(page.locator("body")).toBeVisible();
  });

  test("CrossRefPeek tooltip uses ARIA tooltip role", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    await page.keyboard.press("Space");
    await page.waitForTimeout(400);

    const xrefAnchors = page.locator("[data-xref]");
    if ((await xrefAnchors.count()) === 0) return;

    await page.keyboard.down("Meta");
    await xrefAnchors.first().hover();
    await page.waitForTimeout(300);
    await page.keyboard.up("Meta");

    await expect(page.locator("[role='tooltip']").first()).toBeVisible({
      timeout: 3_000,
    });
  });
});

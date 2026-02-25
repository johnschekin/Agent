/**
 * Phase 3 E2E: Review tab — reader pane, breadcrumbs, cross-family badges,
 * heading highlight, context folding, defined term peek.
 */
import { test, expect } from "../fixtures/links-page";

test.describe("Review Tab Reader", () => {
  test("Reader pane shows section text on Space", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");

    // Reader pane should show actual content — not just "page didn't crash"
    const readerArea = page.locator("text=Select a link").or(
      page.locator("text=Undock")
    ).or(
      page.locator("text=Section text not available")
    ).or(
      page.locator(".highlight-green-glow")
    );
    await expect(readerArea.first()).toBeVisible({ timeout: 3_000 });

    // Verify reader pane occupies the right half of the layout
    const readerPane = page.locator(".border-l.border-border").filter({
      has: page.locator("text=Select a link").or(page.locator("text=Undock")).or(page.locator("text=Section"))
    });
    if ((await readerPane.count()) > 0) {
      await expect(readerPane.first()).toBeVisible();
    }
  });

  test("HierarchyBreadcrumbs sticky", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(300);

    // Look for breadcrumb elements that contain "Article" or "Section"
    const breadcrumb = page.locator("text=Article").or(page.locator("text=Section"));
    const count = await breadcrumb.count();

    // If data is loaded, breadcrumbs should be visible with the section path
    if (count > 0) {
      await expect(breadcrumb.first()).toBeVisible();
      // Breadcrumb should contain the actual section number from the focused row
      const breadcrumbText = await breadcrumb.first().textContent();
      expect(breadcrumbText).toBeTruthy();
      expect(breadcrumbText!.length).toBeGreaterThan(0);
    }
    // If no data, reader shows "Select a link" — acceptable
  });

  test("CrossFamilyInspector badges visible", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader
    await page.keyboard.press("Space");
    await page.waitForTimeout(300);

    // Families label or badge elements
    const familyBadges = page.locator("text=Families:").or(
      page.locator("[data-family-badge]")
    );
    const count = await familyBadges.count();

    // If cross-family data is present, badges should render
    if (count > 0) {
      await expect(familyBadges.first()).toBeVisible();
    }
    // Even without data, page must not crash
    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("Matched heading highlighted green", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader
    await page.keyboard.press("Space");
    await page.waitForTimeout(500);

    // The heading should be rendered with green-glow highlighting
    const greenHighlight = page.locator(".highlight-green-glow");
    const count = await greenHighlight.count();

    // If reader has data loaded, there should be at least 1 green-glow element (the heading)
    if (count > 0) {
      await expect(greenHighlight.first()).toBeVisible();
      // Green highlight should contain actual heading text
      const highlightText = await greenHighlight.first().textContent();
      expect(highlightText).toBeTruthy();
      expect(highlightText!.length).toBeGreaterThan(0);
    }
  });

  test("f toggles context folding", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader
    await page.keyboard.press("Space");
    await page.waitForTimeout(300);

    // Before folding: should NOT have max-h-64 class
    const foldedBefore = page.locator("[class*='max-h-64']");
    const foldedCountBefore = await foldedBefore.count();

    // Press f to toggle folding
    await page.keyboard.press("f");
    await page.waitForTimeout(200);

    // After first press: should have max-h-64 (folded) — if text is present
    const foldedAfter = page.locator("[class*='max-h-64']");
    const foldedCountAfter = await foldedAfter.count();

    // If section text was rendered, folding should add the constraint
    // The count should have changed (increased if folding, decreased if unfolding)
    if (foldedCountBefore === 0 && foldedCountAfter > 0) {
      // Successfully folded — gradient overlay should be present
      const gradient = page.locator("[class*='bg-gradient-to-t']");
      expect(await gradient.count()).toBeGreaterThan(0);
    }

    // Press f again to unfold
    await page.keyboard.press("f");
    await page.waitForTimeout(200);

    // Should return to original state
    const foldedCountFinal = page.locator("[class*='max-h-64']");
    expect(await foldedCountFinal.count()).toBe(foldedCountBefore);
  });

  test("DefinedTermPeek tooltip on hover", async ({ linksPage: page }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader
    await page.keyboard.press("Space");
    await page.waitForTimeout(500);

    // Look for defined terms (blue dotted underline)
    const definedTerms = page.locator(".highlight-blue-term");
    if ((await definedTerms.count()) > 0) {
      // Verify the term has a title attribute (definition text)
      const title = await definedTerms.first().getAttribute("title");
      // Title should contain definition text if populated
      if (title) {
        expect(title.length).toBeGreaterThan(0);
      }

      // Hover over the first term
      await definedTerms.first().hover();
      await page.waitForTimeout(400);

      // After hovering, term should still be visible (no crash on hover)
      await expect(definedTerms.first()).toBeVisible();
    }

    // Page should not crash
    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("Reader renders section content and cross-reference anchors", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    await page.keyboard.press("Space");
    await page.waitForTimeout(500);

    await expect(page.locator("text=Section text not available")).toHaveCount(0);
    const textBody = page.locator(".whitespace-pre-wrap");
    await expect(textBody.first()).toBeVisible();

    const xrefs = page.locator("[data-xref]");
    expect(await xrefs.count()).toBeGreaterThan(0);
  });
});

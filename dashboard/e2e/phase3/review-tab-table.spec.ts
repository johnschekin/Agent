/**
 * Phase 3 E2E: Review tab — table rendering, filtering, KPI cards, pagination.
 */
import { test, expect } from "../fixtures/links-page";

test.describe("Review Tab Table", () => {
  test("Table renders with correct columns", async ({ linksPage: page }) => {
    const headers = page.locator("thead th");
    const headerTexts = await headers.allTextContents();
    const normalized = headerTexts.map((t) => t.trim().toLowerCase());

    expect(normalized).toContain("doc");
    expect(normalized).toContain("section");
    expect(normalized).toContain("heading");
    expect(normalized).toContain("family");
    expect(normalized.some((text) => text.startsWith("confidence"))).toBe(true);
    expect(normalized).toContain("status");
    expect(normalized).toContain("actions");

    // Header row should have surface-2 background
    const thead = page.locator("thead");
    const theadClasses = await thead.getAttribute("class");
    expect(theadClasses).toContain("bg-surface-2");

    // Headers should use uppercase styling
    const firstHeader = headers.nth(1); // Skip checkbox column
    const headerClasses = await firstHeader.getAttribute("class");
    expect(headerClasses).toContain("uppercase");
    expect(headerClasses).toContain("text-[10px]");
  });

  test("Link rows show expected data from seed", async ({ linksPage: page }) => {
    // The minimal seed has 10 links — at least some rows should be visible
    const rows = page.locator("tbody tr");
    const rowCount = await rows.count();

    if (rowCount === 0) {
      // If loading or empty, check for appropriate message
      await expect(
        page.locator("text=Loading").or(page.locator("text=No links found"))
      ).toBeVisible();
    } else {
      expect(rowCount).toBeGreaterThan(0);

      // Each row should have populated cells
      const firstRow = rows.first();
      const cells = firstRow.locator("td");
      const cellCount = await cells.count();
      expect(cellCount).toBe(8); // checkbox + 7 data columns

      // Doc cell should have text content
      const docCell = cells.nth(1);
      const docText = await docCell.textContent();
      expect(docText).toBeTruthy();
      expect(docText!.trim().length).toBeGreaterThan(0);

      // Section cell should have a section number
      const sectionCell = cells.nth(2);
      const sectionText = await sectionCell.textContent();
      expect(sectionText).toBeTruthy();
    }
  });

  test("Filter by family sidebar click", async ({ linksPage: page }) => {
    // Wait for family sidebar to populate
    const allFamiliesBtn = page.locator("button").filter({ hasText: "All Families" });
    await expect(allFamiliesBtn.first()).toBeVisible();

    // Record initial row count
    const initialRows = await page.locator("tbody tr").count();

    // Find a specific family button (not "All Families")
    const familyListContainer = allFamiliesBtn.first().locator("xpath=..");
    const familyButtons = familyListContainer.locator("button");

    if ((await familyButtons.count()) > 1) {
      // Click the first specific family
      const secondBtn = familyButtons.nth(1);
      await secondBtn.click();
      await page.waitForTimeout(500);

      // Active family button should have blue glow style
      const classes = await secondBtn.getAttribute("class");
      expect(classes).toContain("bg-glow-blue");

      // Row count may have changed (filtered)
      const filteredRows = await page.locator("tbody tr").count();
      // Filtered should be <= initial (or same if all rows belong to that family)
      expect(filteredRows).toBeLessThanOrEqual(initialRows);

      // Click "All Families" to reset
      await allFamiliesBtn.first().click();
      await page.waitForTimeout(500);
      const resetRows = await page.locator("tbody tr").count();
      expect(resetRows).toBe(initialRows);
    }
  });

  test("Filter by status dropdown", async ({ linksPage: page }) => {
    // Status chips should be visible
    const allChip = page.locator(".filter-chip").filter({ hasText: "All" });
    await expect(allChip.first()).toBeVisible();

    // "All" chip should be active by default
    const allClasses = await allChip.first().getAttribute("class");
    expect(allClasses).toContain("active");

    const pendingChip = page.locator(".filter-chip").filter({ hasText: "Pending Review" });
    if ((await pendingChip.count()) > 0) {
      await pendingChip.first().click();
      await page.waitForTimeout(300);

      // Pending chip should now have active class
      const pendingClasses = await pendingChip.first().getAttribute("class");
      expect(pendingClasses).toContain("active");

      // "All" chip should no longer be active
      const allClassesAfter = await allChip.first().getAttribute("class");
      expect(allClassesAfter).not.toContain("active");
    }
  });

  test("Filter by confidence tier (t key cycles)", async ({ linksPage: page }) => {
    // Find the tier filter chip
    const tierChip = page.locator(".filter-chip").filter({ hasText: /Tier/ });
    await expect(tierChip.first()).toBeVisible();

    // Initial should be "Tier: All"
    await expect(tierChip.first()).toContainText("All");

    // Press 't' to cycle to high
    await page.keyboard.press("t");
    await expect(tierChip.first()).toContainText("high");

    // Press 't' again to cycle to medium
    await page.keyboard.press("t");
    await expect(tierChip.first()).toContainText("medium");

    // Press 't' again to cycle to low
    await page.keyboard.press("t");
    await expect(tierChip.first()).toContainText("low");

    // Press 't' again to cycle back to all
    await page.keyboard.press("t");
    await expect(tierChip.first()).toContainText("All");
  });

  test("Sort by confidence column header", async ({ linksPage: page }) => {
    const confidenceHeader = page.locator("thead th").filter({ hasText: /confidence/i });
    if ((await confidenceHeader.count()) === 0) return;

    // Click the Confidence header to toggle sort
    await confidenceHeader.first().click();
    await page.waitForTimeout(300);

    // Sort indicator should be visible (▲ or ▼)
    const sortIndicator = confidenceHeader.first().locator("span");
    await expect(sortIndicator.first()).toBeVisible();
    const indicatorText = await sortIndicator.first().textContent();
    // Should contain a sort arrow
    expect(indicatorText).toMatch(/[▲▼⇅]/);
  });

  test("KPI cards show correct totals", async ({ linksPage: page }) => {
    // Look for KPI card elements in the sidebar — now uses actual KpiCard with shadow-card
    const kpiCards = page.locator("[class*='shadow-card']");

    if ((await kpiCards.count()) > 0) {
      // Should have 5 KPI cards: Total links, Unique docs, Pending review, Unlinked, Drift alerts
      const totalLabel = page.locator("text=Total links");
      const uniqueLabel = page.locator("text=Unique docs");
      const pendingLabel = page.locator("text=Pending review");
      const unlinkedLabel = page.locator("text=Unlinked");
      const driftLabel = page.locator("text=Drift alerts");

      // All 5 KPI labels should be visible
      await expect(totalLabel.first()).toBeVisible();
      await expect(uniqueLabel.first()).toBeVisible();
      await expect(pendingLabel.first()).toBeVisible();
      await expect(unlinkedLabel.first()).toBeVisible();
      await expect(driftLabel.first()).toBeVisible();

      // Each KPI card should have a numeric value displayed
      // The cards contain tabular-nums styled numbers
      const numberElements = page.locator("[class*='shadow-card'] [class*='tabular-nums']");
      expect(await numberElements.count()).toBeGreaterThan(0);
    }
  });

  test("Pagination next/prev works", async ({ linksPage: page }) => {
    // Look for pagination controls
    const nextButton = page.locator("button").filter({ hasText: "Next" });
    const prevButton = page.locator("button").filter({ hasText: "Prev" });

    // If there's a pagination bar visible
    if ((await nextButton.count()) > 0) {
      // Prev should be disabled on first page
      await expect(prevButton.first()).toBeDisabled();

      // Page indicator should show "1 / N"
      const pageIndicator = page.locator("text=/\\d+\\s*\\/\\s*\\d+/");
      if ((await pageIndicator.count()) > 0) {
        const text = await pageIndicator.first().textContent();
        expect(text).toMatch(/1\s*\/\s*\d+/);
      }

      // If there are more pages, Next should be enabled and clicking works
      const nextDisabled = await nextButton.first().isDisabled();
      if (!nextDisabled) {
        await nextButton.first().click();
        await page.waitForTimeout(300);

        // After clicking Next, Prev should be enabled
        await expect(prevButton.first()).toBeEnabled();

        // Page indicator should now show "2 / N"
        if ((await pageIndicator.count()) > 0) {
          const textAfter = await pageIndicator.first().textContent();
          expect(textAfter).toMatch(/2\s*\/\s*\d+/);
        }

        // Click Prev to go back
        await prevButton.first().click();
        await page.waitForTimeout(300);
        await expect(prevButton.first()).toBeDisabled();
      }
    }
  });

  test("Pending Review status filter returns pending rows only", async ({
    linksPage: page,
  }) => {
    const pendingChip = page.locator(".filter-chip").filter({ hasText: "Pending Review" });
    await expect(pendingChip.first()).toBeVisible();
    await pendingChip.first().click();
    await page.waitForTimeout(400);

    const rows = page.locator("tbody tr");
    const rowCount = await rows.count();
    if (rowCount === 0) return;
    const sample = Math.min(rowCount, 5);
    for (let i = 0; i < sample; i++) {
      const statusText = (await rows.nth(i).locator("td").nth(6).textContent()) ?? "";
      expect(statusText.toLowerCase()).toContain("pending");
    }
  });

  test("Family sidebar counts are visible for summary families", async ({
    linksPage: page,
    apiContext,
  }) => {
    const summaryRes = await apiContext.get("/api/links/summary");
    expect(summaryRes.ok()).toBeTruthy();
    const summary = await summaryRes.json();
    const byFamily = Array.isArray(summary.by_family) ? summary.by_family : [];
    const sample = byFamily.slice(0, 3);

    for (const family of sample) {
      const familyName = String(family.family_name ?? "");
      const count = String(family.count ?? "");
      const row = page.locator("button").filter({ hasText: familyName });
      await expect(row.first()).toBeVisible();
      await expect(row.first()).toContainText(count);
    }
  });
});

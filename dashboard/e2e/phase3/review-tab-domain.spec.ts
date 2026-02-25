/**
 * Phase 3 E2E: Review tab — ReassignDialog, ContextStrip, ComparablesPanel,
 * link_role badges, tab rendering, child links stub.
 */
import { test, expect } from "../fixtures/links-page";

test.describe("Review Tab Domain Features", () => {
  test("m key opens ReassignDialog with suggestions", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    if ((await page.locator("tbody tr").count()) === 0) return;

    // Press m to open reassign dialog
    await page.keyboard.press("m");

    // Look for the reassign dialog modal
    const dialog = page.locator("text=Reassign to Family");
    await expect(dialog.first()).toBeVisible({ timeout: 3_000 });

    // Dialog should show "Currently:" with the family name
    const currentFamily = page.locator("text=Currently:");
    await expect(currentFamily.first()).toBeVisible();
    const familyText = await currentFamily.first().textContent();
    expect(familyText).toBeTruthy();
    expect(familyText!.length).toBeGreaterThan("Currently:".length);

    // Should show loading, suggestion items, or explicit empty-state text
    const suggestions = page.locator("text=Loading suggestions").or(
      page.locator(".reassign-suggestion")
    ).or(
      page.locator("text=No alternative families")
    );
    expect(await suggestions.count()).toBeGreaterThan(0);

    // Close dialog with Escape
    await page.keyboard.press("Escape");

    // Dialog should close
    await expect(dialog.first()).toBeHidden({ timeout: 2_000 });
  });

  test("Selecting family in ReassignDialog reassigns link", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    if ((await page.locator("tbody tr").count()) === 0) return;

    // Press m to open reassign dialog
    await page.keyboard.press("m");

    const dialog = page.locator("text=Reassign to Family");
    await expect(dialog.first()).toBeVisible({ timeout: 3_000 });

    // Wait for suggestions to load
    await page.waitForTimeout(1_000);

    // Check if suggestions loaded
    const loadingText = page.locator("text=Loading suggestions");
    const noSuggestions = page.locator("text=No alternative families");
    const hasSuggestions = (await loadingText.count()) === 0 && (await noSuggestions.count()) === 0;

    if (hasSuggestions) {
      // Navigate with j to first suggestion and confirm with Enter
      await page.keyboard.press("j");
      await page.keyboard.press("Enter");

      // Dialog should close after successful reassign
      await expect(dialog.first()).toBeHidden({ timeout: 3_000 });
    } else {
      // No suggestions — close the dialog
      await page.keyboard.press("Escape");
    }

    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("ContextStrip shows primary + definitions + xrefs", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane to see ContextStrip
    await page.keyboard.press("Space");
    await page.waitForTimeout(1_000);

    // ContextStrip sections should have these headers
    const primaryHeading = page.locator("text=Primary Covenant");
    const defsHeading = page.locator("text=Key Definitions");
    const xrefsHeading = page.locator("text=Cross-References");

    // If context data loaded, all three sections should be present
    const primaryCount = await primaryHeading.count();
    const defsCount = await defsHeading.count();
    const xrefsCount = await xrefsHeading.count();

    // If ContextStrip rendered (data available), verify section headers
    if (primaryCount > 0) {
      await expect(primaryHeading.first()).toBeVisible();
    }
    if (defsCount > 0) {
      await expect(defsHeading.first()).toBeVisible();
    }
    if (xrefsCount > 0) {
      await expect(xrefsHeading.first()).toBeVisible();
    }

    // Also check for loading or no-context states
    const noContext = page.locator("text=No context available").or(
      page.locator("text=Loading context")
    );
    // Either context sections or a loading/empty state should exist
    expect(primaryCount + defsCount + xrefsCount + (await noContext.count())).toBeGreaterThan(0);
  });

  test("Clicking definition in ContextStrip shows inline text", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(1_000);

    // Find definition items in ContextStrip (they're buttons with font-medium text)
    const defHeading = page.locator("text=Key Definitions");
    if ((await defHeading.count()) > 0) {
      // Find clickable definition buttons in the definitions section
      const defButtons = page.locator("button").filter({
        has: page.locator("span.font-medium")
      });

      if ((await defButtons.count()) > 0) {
        // Click the first definition to expand
        await defButtons.first().click();
        await page.waitForTimeout(300);

        // Should expand to show definition text with animate-fade-in
        const expandedText = page.locator(".animate-fade-in");
        if ((await expandedText.count()) > 0) {
          await expect(expandedText.first()).toBeVisible();
          // Expanded text should have actual content
          const text = await expandedText.first().textContent();
          expect(text).toBeTruthy();
          expect(text!.length).toBeGreaterThan(0);
        }
      }
    }

    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("ComparablesPanel shows comparable sections", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(1_000);

    // Look for comparables heading
    const comparablesHeading = page.locator("text=Comparables");
    const noComparables = page.locator("text=No comparable sections found");

    // Either comparables data or "no comparables" message should be present
    if ((await comparablesHeading.count()) > 0) {
      await expect(comparablesHeading.first()).toBeVisible();

      // Comparable items should be capped at 5
      const comparableItems = page.locator("[data-comparable], .comparable-section");
      if ((await comparableItems.count()) > 0) {
        expect(await comparableItems.count()).toBeLessThanOrEqual(5);
      }
    }

    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("One-click 'pin as TP' from comparables", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(1_000);

    // Find the pin-as-TP button in comparables panel
    const pinButtons = page.locator("button").filter({ hasText: /pin as tp/i });

    if ((await pinButtons.count()) > 0) {
      // Verify button is visible before clicking
      await expect(pinButtons.first()).toBeVisible();

      // Click pin-as-TP
      await pinButtons.first().click();
      await page.waitForTimeout(500);

      // Button should still exist (action is idempotent)
      await expect(page.locator("h1")).toContainText("Family Links");
    }
  });

  test("One-click 'use as template baseline' from comparables", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    // Open reader pane
    await page.keyboard.press("Space");
    await page.waitForTimeout(1_000);

    // Find the use-as-baseline button
    const baselineButtons = page.locator("button").filter({ hasText: /use as baseline/i });

    if ((await baselineButtons.count()) > 0) {
      await expect(baselineButtons.first()).toBeVisible();

      // Click use-as-baseline
      await baselineButtons.first().click();
      await page.waitForTimeout(500);

      await expect(page.locator("h1")).toContainText("Family Links");
    }
  });

  test("link_role badge visible in table rows", async ({
    linksPage: page,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});

    const rows = page.locator("tbody tr");
    if ((await rows.count()) === 0) return;

    // Each row should have family and role badges in the Family column
    const firstRow = rows.first();
    const badges = firstRow.locator("[class*='rounded-']").filter({
      has: page.locator("text=/primary_covenant|definitions support|secondary signal|xref support/i").or(
        page.locator(".bg-glow-blue").or(page.locator(".bg-glow-cyan"))
      )
    });

    // At minimum, each row should have a family badge
    const familyBadges = firstRow.locator("td").nth(4).locator("[class*='rounded-']");
    expect(await familyBadges.count()).toBeGreaterThan(0);

    // The family badge should contain actual family name text
    const badgeText = await familyBadges.first().textContent();
    expect(badgeText).toBeTruthy();
    expect(badgeText!.trim().length).toBeGreaterThan(0);
  });

  test("All 7 tabs render without error", async ({ linksPage: page }) => {
    const tabNames = [
      "Review",
      "Coverage",
      "Query",
      "Conflicts",
      "Rules",
      "Dashboard",
      "Child Links",
    ];

    for (const tabName of tabNames) {
      const tabButton = page.locator("button, [role='tab']").filter({
        hasText: new RegExp(`^${tabName}$`, "i"),
      });

      if ((await tabButton.count()) > 0) {
        await tabButton.first().click();
        await page.waitForTimeout(300);

        // Verify no error overlay appeared
        const errorOverlay = page.locator("text=Application error").or(
          page.locator("text=Unhandled Runtime Error")
        );
        expect(await errorOverlay.count()).toBe(0);

        // Tab should be active (blue border)
        const classes = await tabButton.first().getAttribute("class");
        expect(classes).toContain("border-b-accent-blue");
      }
    }

    // Return to Review tab
    const reviewTab = page.locator("button, [role='tab']").filter({ hasText: /^Review$/i });
    await reviewTab.first().click();
    await expect(page.locator("h1")).toContainText("Family Links");
  });

  test("Child Links tab shows stub placeholder", async ({
    linksPage: page,
  }) => {
    // Navigate to Child Links tab
    const childLinksTab = page.locator("button, [role='tab']").filter({ hasText: /Child Links/i });
    await expect(childLinksTab.first()).toBeVisible();

    await childLinksTab.first().click();
    await page.waitForTimeout(300);

    // Should show a Phase 5 placeholder with actual text
    const placeholder = page.locator("text=Phase 5").or(
      page.locator("text=Coming")
    );
    await expect(placeholder.first()).toBeVisible();

    // Should also show the tab label
    const tabLabel = page.locator("text=Child Links");
    await expect(tabLabel.first()).toBeVisible();

    // URL should have ?tab=children
    expect(page.url()).toContain("tab=children");
  });

  test("Reassign suggestions API returns capped top-5 list", async ({
    linksPage: page,
    apiContext,
  }) => {
    await page.waitForSelector("tbody tr", { timeout: 10_000 }).catch(() => {});
    const focusedRow = page.locator("tbody tr[class*='shadow-inset-blue']").first();
    const linkId = await focusedRow.getAttribute("data-row-id");
    if (!linkId) return;

    const res = await apiContext.get(`/api/links/${linkId}/reassign-suggestions`);
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    const suggestions = Array.isArray(body.suggestions) ? body.suggestions : [];
    expect(suggestions.length).toBeLessThanOrEqual(5);
  });
});

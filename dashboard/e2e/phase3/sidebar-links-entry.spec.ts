/**
 * Phase 3 E2E: Sidebar icon rail shows Linking module.
 *
 * Tests that the sidebar shows the Linking module icon,
 * has active state on /links, and not active on other pages.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Sidebar Links Entry", () => {
  test("Sidebar icon rail shows Linking module", async ({ linksPage: page }) => {
    // The Linking icon button should be visible
    const linkingButton = page.locator('button[title="Linking"]');
    await expect(linkingButton).toBeVisible();
  });

  test("Linking icon has active state on /links page", async ({ linksPage: page }) => {
    // The Linking button should have the blue glow class when on /links
    const linkingButton = page.locator('button[title="Linking"]');
    // Active state: contains accent-blue text color or glow
    const classes = await linkingButton.getAttribute("class");
    expect(classes).toContain("text-accent-blue");
  });

  test("Clicking Linking icon shows flyout with Family Links entry", async ({
    linksPage: page,
  }) => {
    const linkingButton = page.locator('button[title="Linking"]');
    await linkingButton.click();
    const familyLinksEntry = page.locator("text=Family Links");
    await expect(familyLinksEntry.first()).toBeVisible();
  });

  test("Linking icon is not active on other pages", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/overview`);
    await page.waitForLoadState("networkidle");

    const linkingButton = page.locator('button[title="Linking"]');
    await expect(linkingButton).toBeVisible();

    // On /overview, the Linking button should NOT have active state
    const classes = await linkingButton.getAttribute("class");
    // When not active, it should have text-text-muted
    expect(classes).toContain("text-text-muted");
  });
});

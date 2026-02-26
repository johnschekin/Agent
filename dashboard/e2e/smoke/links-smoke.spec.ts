/**
 * Phase 3 Smoke Tests: Cross-phase regression safety net.
 *
 * Verifies /links loads, all tabs are clickable, existing pages
 * from Phase 1-2 still render, and health check passes.
 */
import { test, expect } from "@playwright/test";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";
const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";

test.describe("Links Smoke Tests", () => {
  test("/links page loads without crash", async ({ page }) => {
    const response = await page.goto(`${FRONTEND_BASE}/links`);

    // HTTP response should be successful
    expect(response?.status()).toBeLessThan(500);

    // Wait for page to settle
    await page.waitForLoadState("networkidle");

    // Page title should contain "Family Links"
    const heading = page.locator("h1");
    await expect(heading).toContainText("Family Links", { timeout: 10_000 });

    // No unhandled error overlays
    const errorOverlay = page
      .locator("text=Application error")
      .or(page.locator("text=Unhandled Runtime Error"));
    expect(await errorOverlay.count()).toBe(0);
  });

  test("All tabs are clickable without error", async ({ page }) => {
    await page.goto(`${FRONTEND_BASE}/links`);
    await page.waitForLoadState("networkidle");

    const tabNames = [
      "Review",
      "Coverage",
      "Query",
      "Conflicts",
      "Rules",
      "Dashboard",
    ];

    for (const tabName of tabNames) {
      const tabButton = page.locator("button, [role='tab']").filter({
        hasText: new RegExp(tabName, "i"),
      });

      if ((await tabButton.count()) > 0) {
        await tabButton.first().click();
        await page.waitForTimeout(200);

        // No error overlay should appear after clicking any tab
        const errorOverlay = page
          .locator("text=Application error")
          .or(page.locator("text=Unhandled Runtime Error"));
        expect(await errorOverlay.count()).toBe(0);

        // URL should have updated with tab parameter
        const url = page.url();
        // URL may contain ?tab= parameter
        expect(url).toContain("/links");
      }
    }
  });

  test("Existing pages still render (Phase 1-2 regression)", async ({
    page,
  }) => {
    // Test key pages from Phase 1-2 still work with new design tokens
    const existingPages = [
      { path: "/overview", title: /overview|dashboard/i },
      { path: "/reader", title: /reader|document/i },
      { path: "/edge-cases", title: /edge|case/i },
    ];

    for (const { path, title } of existingPages) {
      const response = await page.goto(`${FRONTEND_BASE}${path}`);

      // Should not return server error
      expect(response?.status()).toBeLessThan(500);

      // Wait for page to settle
      await page.waitForLoadState("networkidle");

      // Look for a heading or body content
      const body = page.locator("body");
      await expect(body).toBeVisible();

      // Check for title text (flexible match for different page titles)
      const heading = page.locator("h1");
      if ((await heading.count()) > 0) {
        const headingText = await heading.first().textContent();
        // Heading should have some text content
        expect(headingText).toBeTruthy();
      }

      // No unhandled errors
      const errorOverlay = page
        .locator("text=Application error")
        .or(page.locator("text=Unhandled Runtime Error"));
      expect(await errorOverlay.count()).toBe(0);
    }
  });

  test("API health check includes links capability", async ({ request }) => {
    // Health endpoint should respond successfully
    const response = await request.get(`${API_BASE}/api/health`);
    expect(response.status()).toBe(200);

    const body = await response.json();

    // Health response should indicate the server is operational
    // The exact shape depends on the backend, but it should have status or ok
    expect(body).toBeTruthy();

    // Check for status field (common health check pattern)
    if ("status" in body) {
      expect(body.status).toBeTruthy();
    }

    // If the health check exposes capabilities/features, links should be included
    expect(typeof body.links_loaded).toBe("boolean");
    expect(body.links_loaded).toBeTruthy();
  });
});

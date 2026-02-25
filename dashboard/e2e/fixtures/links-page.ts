/**
 * Phase 3 Playwright fixture for browser-based links page tests.
 *
 * Extends the links-db fixture to also provide a `page` that navigates
 * to the frontend (localhost:3000). Seeds data via the API backend,
 * then tests the rendered Next.js UI.
 */
import { test as linksTest, type LinksFixtures } from "./links-db";
import type { Page } from "@playwright/test";

export { expect } from "@playwright/test";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

export type LinksPageFixtures = LinksFixtures & {
  linksPage: Page;
};

export const test = linksTest.extend<LinksPageFixtures>({
  linksPage: async ({ page, resetLinks, seedLinks }, use) => {
    // Seed deterministic data
    await resetLinks();
    await seedLinks("minimal");
    // Navigate to links page
    await page.goto(`${FRONTEND_BASE}/links`);
    await page.waitForLoadState("networkidle");
    await use(page);
  },
});

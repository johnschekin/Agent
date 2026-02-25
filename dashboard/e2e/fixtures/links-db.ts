/**
 * Custom Playwright fixture for link database seeding and teardown.
 *
 * Provides:
 * - apiContext: an APIRequestContext pre-configured with the backend base URL
 * - seedLinks(dataset): insert a named deterministic dataset via POST /api/links/_test/seed
 * - resetLinks(): truncate all link tables via POST /api/links/_test/reset
 *
 * Usage in test files:
 *   import { test } from "../fixtures/links-db";
 *
 *   test.describe("My API tests", () => {
 *     test.beforeEach(async ({ resetLinks, seedLinks }) => {
 *       await resetLinks();
 *       await seedLinks("minimal");
 *     });
 *
 *     test("should list links", async ({ apiContext }) => {
 *       const res = await apiContext.get("/api/links");
 *       expect(res.ok()).toBeTruthy();
 *     });
 *   });
 */
import { test as base, expect, type APIRequestContext } from "@playwright/test";

const API_BASE = process.env.API_BASE_URL ?? "http://localhost:8000";
const LINKS_API_TOKEN = process.env.LINKS_API_TOKEN ?? "local-dev-links-token";
const LINKS_ADMIN_TOKEN = process.env.LINKS_ADMIN_TOKEN ?? LINKS_API_TOKEN;
const LINKS_TEST_ENDPOINT_TOKEN =
  process.env.LINKS_TEST_ENDPOINT_TOKEN ?? LINKS_ADMIN_TOKEN;

/**
 * Named seed datasets (deterministic IDs for test assertions):
 * - "minimal": 3 families, 10 links
 * - "review": 50 links with varied statuses/tiers
 * - "conflicts": 20 links with 5 deliberate conflicts
 * - "coverage": 8 families, 100 sections, varied coverage
 * - "rules": 10 rules with varied statuses/pins
 * - "full": union of all + 3 pending jobs
 */
export type SeedDataset =
  | "minimal"
  | "review"
  | "conflicts"
  | "coverage"
  | "rules"
  | "full";

export type LinksFixtures = {
  apiContext: APIRequestContext;
  seedLinks: (dataset: SeedDataset) => Promise<void>;
  resetLinks: () => Promise<void>;
};

export const test = base.extend<LinksFixtures>({
  apiContext: async ({ playwright }, use) => {
    const context = await playwright.request.newContext({
      baseURL: API_BASE,
      extraHTTPHeaders: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-Links-Token": LINKS_ADMIN_TOKEN,
      },
    });
    await use(context);
    await context.dispose();
  },

  seedLinks: async ({ apiContext }, use) => {
    const seed = async (dataset: SeedDataset) => {
      const res = await apiContext.post("/api/links/_test/seed", {
        data: { dataset },
        headers: { "X-Links-Token": LINKS_TEST_ENDPOINT_TOKEN },
      });
      if (!res.ok()) {
        const body = await res.text();
        throw new Error(
          `Failed to seed dataset "${dataset}": ${res.status()} ${body}`,
        );
      }
    };
    await use(seed);
  },

  resetLinks: async ({ apiContext }, use) => {
    const reset = async () => {
      const res = await apiContext.post("/api/links/_test/reset", {
        headers: { "X-Links-Token": LINKS_TEST_ENDPOINT_TOKEN },
      });
      if (!res.ok()) {
        const body = await res.text();
        throw new Error(`Failed to reset links: ${res.status()} ${body}`);
      }
    };
    await use(reset);
  },
});

export { expect };

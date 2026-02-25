/**
 * Phase 2 E2E: Links query, filter, and sort operations.
 *
 * Tests filtering by family, status, confidence tier, and sorting.
 * Also covers the families summary and coverage-gap endpoints.
 * All tests use the deterministic "minimal" seed dataset (10 links, 3 families).
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES } from "../fixtures/seed-data";
import {
  expectOk,
  expectValidLink,
  expectPaginated,
  expectSortedDesc,
  expectAll,
  expectValidTier,
} from "../helpers/link-assertions";

test.describe("Links Query & Filter API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // ── 1. Filter by family_id ────────────────────────────────

  test("Filter by family_id — GET /api/links?family_id=FAM-indebtedness", async ({
    apiContext,
  }) => {
    const res = await apiContext.get(
      `/api/links?family_id=${FAMILIES.indebtedness}`,
    );
    expectOk(res);

    const body = await res.json();
    expectPaginated(body);
    expect(Array.isArray(body.items)).toBe(true);

    // All returned links must belong to the indebtedness family
    expectAll(
      body.items,
      (item: Record<string, unknown>) =>
        item.family_id === FAMILIES.indebtedness,
      "All items should have family_id = FAM-indebtedness",
    );

    // Minimal dataset has 3 indebtedness links: LINK-001, LINK-002, LINK-007
    const expectedCount = MINIMAL_LINKS.filter(
      (l) => l.family_id === FAMILIES.indebtedness,
    ).length;
    expect(body.total).toBe(expectedCount);
  });

  // ── 2. Filter by status ───────────────────────────────────

  test("Filter by status — GET /api/links?status=active", async ({
    apiContext,
  }) => {
    const res = await apiContext.get("/api/links?status=active");
    expectOk(res);

    const body = await res.json();
    expectPaginated(body);

    // All returned links must be active
    expectAll(
      body.items,
      (item: Record<string, unknown>) => item.status === "active",
      "All items should have status=active",
    );

    // Count active links in seed data
    const activeCount = MINIMAL_LINKS.filter(
      (l) => l.status === "active",
    ).length;
    expect(body.total).toBe(activeCount);
  });

  // ── 3. Filter by confidence_tier ──────────────────────────

  test("Filter by confidence_tier — GET /api/links?confidence_tier=high", async ({
    apiContext,
  }) => {
    const res = await apiContext.get("/api/links?confidence_tier=high");
    expectOk(res);

    const body = await res.json();
    expectPaginated(body);

    // All returned links must have high confidence tier
    expectAll(
      body.items,
      (item: Record<string, unknown>) => item.confidence_tier === "high",
      "All items should have confidence_tier=high",
    );

    for (const link of body.items) {
      expectValidLink(link);
      expectValidTier(link.confidence_tier);
    }

    // Count high-confidence links in seed data
    const highCount = MINIMAL_LINKS.filter(
      (l) => l.confidence_tier === "high",
    ).length;
    expect(body.total).toBe(highCount);
  });

  // ── 4. Sort by confidence DESC ────────────────────────────

  test("Sort by confidence DESC — GET /api/links?sort_by=confidence&sort_dir=desc", async ({
    apiContext,
  }) => {
    const res = await apiContext.get(
      "/api/links?sort_by=confidence&sort_dir=desc",
    );
    expectOk(res);

    const body = await res.json();
    expectPaginated(body);
    expect(body.items.length).toBeGreaterThan(1);

    // Verify descending order by confidence
    expectSortedDesc(body.items, "confidence");
  });

  // ── 5. Families summary ───────────────────────────────────

  test("GET /api/links/families summary — returns family breakdown", async ({
    apiContext,
  }) => {
    const res = await apiContext.get("/api/links/families");
    expectOk(res);

    const body = await res.json();
    expect(Array.isArray(body)).toBe(true);

    // Should have at least the families present in the minimal dataset
    const seedFamilyIds = Array.from(
      new Set(MINIMAL_LINKS.map((l) => l.family_id)),
    );
    expect(body.length).toBeGreaterThanOrEqual(seedFamilyIds.length);

    // Each family summary should include an id, total count, and breakdown
    for (const family of body) {
      expect(family).toHaveProperty("family_id");
      expect(family).toHaveProperty("total");
      expect(typeof family.total).toBe("number");
      expect(family.total).toBeGreaterThan(0);
    }

    // Verify indebtedness count
    const indebt = body.find(
      (f: Record<string, unknown>) => f.family_id === FAMILIES.indebtedness,
    );
    expect(indebt).toBeDefined();
    const expectedIndebtCount = MINIMAL_LINKS.filter(
      (l) => l.family_id === FAMILIES.indebtedness,
    ).length;
    expect(indebt.total).toBe(expectedIndebtCount);
  });

  // ── 6. Coverage with gaps + "why not" ─────────────────────

  test("GET /api/links/coverage with gaps + why not — returns coverage gaps", async ({
    apiContext,
  }) => {
    const res = await apiContext.get("/api/links/coverage");
    expectOk(res);

    const body = await res.json();

    // Coverage response should have families or sections with gap info
    expect(body).toHaveProperty("families");
    expect(Array.isArray(body.families)).toBe(true);

    for (const entry of body.families) {
      expect(entry).toHaveProperty("family_id");
      expect(entry).toHaveProperty("doc_count");
      expect(typeof entry.doc_count).toBe("number");

      // Each family entry should include a gaps array with "why_not" reasons
      expect(entry).toHaveProperty("gaps");
      expect(Array.isArray(entry.gaps)).toBe(true);

      for (const gap of entry.gaps) {
        expect(gap).toHaveProperty("doc_id");
        expect(gap).toHaveProperty("why_not");
        expect(typeof gap.why_not).toBe("string");
      }
    }
  });
});

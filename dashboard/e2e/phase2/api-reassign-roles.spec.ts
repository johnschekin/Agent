/**
 * Phase 2 E2E: Reassign roles, context strips, and defined terms.
 *
 * Tests family reassignment, suggestion ranking, audit trail preservation,
 * context-strip retrieval, and defined-term binding.
 * All tests use the deterministic "minimal" seed dataset (10 links, 3 families).
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES } from "../fixtures/seed-data";
import { expectOk, expectValidLink } from "../helpers/link-assertions";

test.describe("Reassign Roles API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // ── 1. Reassign link to new family ─────────────────────────

  test("POST /api/links/{id}/reassign moves link to new family", async ({
    apiContext,
  }) => {
    const linkId = "LINK-001"; // currently FAM-indebtedness
    const newFamilyId = FAMILIES.liens;

    const res = await apiContext.post(`/api/links/${linkId}/reassign`, {
      data: { family_id: newFamilyId },
    });
    expectOk(res);

    const body = await res.json();
    expect(body.link_id).toBe(linkId);
    expect(body.family_id).toBe(newFamilyId);

    // Confirm persistence via GET
    const getRes = await apiContext.get(`/api/links/${linkId}`);
    expectOk(getRes);
    const getBody = await getRes.json();
    expect(getBody.family_id).toBe(newFamilyId);
  });

  // ── 2. Reassign suggestions ────────────────────────────────

  test("GET /api/links/{id}/reassign-suggestions returns top 5", async ({
    apiContext,
  }) => {
    const linkId = "LINK-001";

    const res = await apiContext.get(
      `/api/links/${linkId}/reassign-suggestions`,
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("suggestions");
    expect(Array.isArray(body.suggestions)).toBe(true);
    expect(body.suggestions.length).toBeLessThanOrEqual(5);

    // Each suggestion should have a family_id and a score
    for (const suggestion of body.suggestions) {
      expect(suggestion).toHaveProperty("family_id");
      expect(suggestion).toHaveProperty("score");
      expect(typeof suggestion.score).toBe("number");
    }

    // The current family should not appear in suggestions
    const currentFamilyIds = body.suggestions.map(
      (s: Record<string, unknown>) => s.family_id,
    );
    expect(currentFamilyIds).not.toContain(FAMILIES.indebtedness);
  });

  // ── 3. Reassign preserves audit trail ──────────────────────

  test("Reassign preserves audit trail", async ({ apiContext }) => {
    const linkId = "LINK-003"; // currently FAM-liens
    const newFamilyId = FAMILIES.dividends;

    // Perform reassignment
    const reassignRes = await apiContext.post(
      `/api/links/${linkId}/reassign`,
      { data: { family_id: newFamilyId } },
    );
    expectOk(reassignRes);

    // Fetch the link with events
    const getRes = await apiContext.get(`/api/links/${linkId}`);
    expectOk(getRes);
    const body = await getRes.json();

    expect(body).toHaveProperty("events");
    expect(Array.isArray(body.events)).toBe(true);

    // Find the reassign event in the audit trail
    const reassignEvent = body.events.find(
      (e: Record<string, unknown>) => e.action === "reassign",
    );
    expect(reassignEvent).toBeDefined();
    expect(reassignEvent.previous_family_id).toBe(FAMILIES.liens);
    expect(reassignEvent.new_family_id).toBe(newFamilyId);
  });

  // ── 4. Context strip ───────────────────────────────────────

  test("GET /api/links/{id}/context-strip returns primary+definitions+xrefs", async ({
    apiContext,
  }) => {
    const linkId = "LINK-001";

    const res = await apiContext.get(`/api/links/${linkId}/context-strip`);
    expectOk(res);

    const body = await res.json();

    // Must contain the three context components
    expect(body).toHaveProperty("primary");
    expect(body).toHaveProperty("definitions");
    expect(body).toHaveProperty("xrefs");

    // Primary should contain section text content
    expect(body.primary).toHaveProperty("section_number");
    expect(body.primary).toHaveProperty("text");
    expect(typeof body.primary.text).toBe("string");

    // Definitions and xrefs are arrays
    expect(Array.isArray(body.definitions)).toBe(true);
    expect(Array.isArray(body.xrefs)).toBe(true);
  });

  // ── 5. Bind defined terms ──────────────────────────────────

  test("POST /api/links/{id}/defined-terms binds terms", async ({
    apiContext,
  }) => {
    const linkId = "LINK-001";
    const terms = [
      { term: "Permitted Indebtedness", char_start: 100, char_end: 122 },
      { term: "Total Net Leverage Ratio", char_start: 250, char_end: 274 },
    ];

    const res = await apiContext.post(
      `/api/links/${linkId}/defined-terms`,
      { data: { terms } },
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("bound");
    expect(body.bound).toBe(2);
  });

  // ── 6. Retrieve defined terms ──────────────────────────────

  test("GET /api/links/{id}/defined-terms retrieves them", async ({
    apiContext,
  }) => {
    const linkId = "LINK-001";

    // First bind some terms
    const terms = [
      { term: "Permitted Indebtedness", char_start: 100, char_end: 122 },
      { term: "Total Net Leverage Ratio", char_start: 250, char_end: 274 },
    ];
    await apiContext.post(`/api/links/${linkId}/defined-terms`, {
      data: { terms },
    });

    // Now retrieve them
    const res = await apiContext.get(`/api/links/${linkId}/defined-terms`);
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("terms");
    expect(Array.isArray(body.terms)).toBe(true);
    expect(body.terms.length).toBe(2);

    // Verify each term has the expected shape
    for (const t of body.terms) {
      expect(t).toHaveProperty("term");
      expect(t).toHaveProperty("char_start");
      expect(t).toHaveProperty("char_end");
      expect(typeof t.term).toBe("string");
      expect(typeof t.char_start).toBe("number");
      expect(typeof t.char_end).toBe("number");
    }

    const returnedTermNames = body.terms.map(
      (t: Record<string, unknown>) => t.term,
    );
    expect(returnedTermNames).toContain("Permitted Indebtedness");
    expect(returnedTermNames).toContain("Total Net Leverage Ratio");
  });

  // ── 7. Reassign with invalid family_id ─────────────────────

  test("Reassign with invalid family_id returns 404", async ({
    apiContext,
  }) => {
    const linkId = "LINK-001";

    const res = await apiContext.post(`/api/links/${linkId}/reassign`, {
      data: { family_id: "FAM-nonexistent" },
    });

    expect(res.status()).toBe(404);

    const body = await res.json();
    expect(body).toHaveProperty("detail");
  });

  // ── 8. link_role defaults to primary_covenant ──────────────

  test("link_role defaults to primary_covenant", async ({ apiContext }) => {
    const linkId = "LINK-001";

    // Reassign without specifying link_role
    const reassignRes = await apiContext.post(
      `/api/links/${linkId}/reassign`,
      { data: { family_id: FAMILIES.dividends } },
    );
    expectOk(reassignRes);

    const body = await reassignRes.json();
    expect(body).toHaveProperty("link_role");
    expect(body.link_role).toBe("primary_covenant");

    // Also verify via GET
    const getRes = await apiContext.get(`/api/links/${linkId}`);
    expectOk(getRes);
    const getBody = await getRes.json();
    expect(getBody.link_role).toBe("primary_covenant");
  });
});

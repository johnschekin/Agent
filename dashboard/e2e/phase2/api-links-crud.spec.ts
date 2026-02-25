/**
 * Phase 2 E2E: Links CRUD operations.
 *
 * Tests the core link lifecycle — create, read, unlink, relink, batch ops.
 * All tests use the deterministic "minimal" seed dataset (10 links, 3 families).
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES } from "../fixtures/seed-data";
import {
  expectOk,
  expectValidLink,
  expectPaginated,
} from "../helpers/link-assertions";

test.describe("Links CRUD API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // ── 1. Paginated list ─────────────────────────────────────

  test("GET /api/links paginated — returns items array + total", async ({
    apiContext,
  }) => {
    const res = await apiContext.get("/api/links");
    expectOk(res);

    const body = await res.json();
    expectPaginated(body);
    expect(body.items).toBeDefined();
    expect(Array.isArray(body.items)).toBe(true);
    expect(body.total).toBe(MINIMAL_LINKS.length);

    // Each returned link must have the required fields
    for (const link of body.items) {
      expectValidLink(link);
    }
  });

  // ── 2. Single link with events ────────────────────────────

  test("GET /api/links/{id} with events — returns link + events array", async ({
    apiContext,
  }) => {
    const linkId = MINIMAL_LINKS[0].link_id; // LINK-001
    const res = await apiContext.get(`/api/links/${linkId}`);
    expectOk(res);

    const body = await res.json();
    expectValidLink(body);
    expect(body.link_id).toBe(linkId);
    expect(body.family_id).toBe(FAMILIES.indebtedness);
    expect(body.section_number).toBe("7.01");
    expect(body.confidence).toBe(0.92);

    // Events array must be present (at least a "created" event from seeding)
    expect(body).toHaveProperty("events");
    expect(Array.isArray(body.events)).toBe(true);
  });

  // ── 3. Create manual link ─────────────────────────────────

  test("POST /api/links manual link — creates with all required fields", async ({
    apiContext,
  }) => {
    const newLink = {
      family_id: FAMILIES.investments,
      doc_id: "DOC-010",
      section_number: "7.04",
      heading: "Permitted Investments",
      confidence: 0.95,
      confidence_tier: "high",
      status: "active",
    };

    const res = await apiContext.post("/api/links", { data: newLink });
    expectOk(res);

    const body = await res.json();
    expectValidLink(body);
    expect(body.family_id).toBe(newLink.family_id);
    expect(body.doc_id).toBe(newLink.doc_id);
    expect(body.section_number).toBe(newLink.section_number);
    expect(body.heading).toBe(newLink.heading);
    expect(body.confidence).toBe(newLink.confidence);
    expect(body.confidence_tier).toBe(newLink.confidence_tier);
    expect(body.status).toBe("active");
    // Must return a generated link_id
    expect(body.link_id).toBeTruthy();

    // Verify it appears in the full list
    const listRes = await apiContext.get("/api/links");
    const listBody = await listRes.json();
    expect(listBody.total).toBe(MINIMAL_LINKS.length + 1);
  });

  // ── 4. Unlink with reason ─────────────────────────────────

  test("PATCH /api/links/{id}/unlink with reason — sets status=unlinked + records reason", async ({
    apiContext,
  }) => {
    const linkId = "LINK-001"; // currently active
    const reason = "Heading does not match ontology definition";

    const res = await apiContext.patch(`/api/links/${linkId}/unlink`, {
      data: { reason },
    });
    expectOk(res);

    const body = await res.json();
    expect(body.link_id).toBe(linkId);
    expect(body.status).toBe("unlinked");

    // Fetch the link again to confirm persistence + reason in events
    const getRes = await apiContext.get(`/api/links/${linkId}`);
    const getBody = await getRes.json();
    expect(getBody.status).toBe("unlinked");
    expect(getBody.events).toBeDefined();

    const unlinkEvent = getBody.events.find(
      (e: Record<string, unknown>) => e.action === "unlink",
    );
    expect(unlinkEvent).toBeDefined();
    expect(unlinkEvent.reason).toBe(reason);
  });

  // ── 5. Relink ─────────────────────────────────────────────

  test("PATCH /api/links/{id}/relink — sets status back to active", async ({
    apiContext,
  }) => {
    // LINK-009 is seeded as "unlinked"
    const linkId = "LINK-009";

    // Confirm it starts as unlinked
    const beforeRes = await apiContext.get(`/api/links/${linkId}`);
    const beforeBody = await beforeRes.json();
    expect(beforeBody.status).toBe("unlinked");

    // Relink it
    const res = await apiContext.patch(`/api/links/${linkId}/relink`);
    expectOk(res);

    const body = await res.json();
    expect(body.link_id).toBe(linkId);
    expect(body.status).toBe("active");

    // Confirm persistence
    const afterRes = await apiContext.get(`/api/links/${linkId}`);
    const afterBody = await afterRes.json();
    expect(afterBody.status).toBe("active");
  });

  // ── 6. Batch unlink ───────────────────────────────────────

  test("POST /api/links/batch/unlink — batch unlinks multiple links", async ({
    apiContext,
  }) => {
    const linkIds = ["LINK-001", "LINK-002", "LINK-003"];
    const reason = "Batch removal — low relevance";

    const res = await apiContext.post("/api/links/batch/unlink", {
      data: { link_ids: linkIds, reason },
    });
    expectOk(res);

    const body = await res.json();
    expect(body.updated).toBe(linkIds.length);

    // Verify each link is now unlinked
    for (const id of linkIds) {
      const checkRes = await apiContext.get(`/api/links/${id}`);
      const checkBody = await checkRes.json();
      expect(checkBody.status).toBe("unlinked");
    }
  });

  // ── 7. Batch relink ───────────────────────────────────────

  test("POST /api/links/batch/relink — batch relinks multiple links", async ({
    apiContext,
  }) => {
    // First batch-unlink LINK-001 and LINK-002 so we can relink them
    await apiContext.post("/api/links/batch/unlink", {
      data: { link_ids: ["LINK-001", "LINK-002"], reason: "setup" },
    });

    const res = await apiContext.post("/api/links/batch/relink", {
      data: { link_ids: ["LINK-001", "LINK-002"] },
    });
    expectOk(res);

    const body = await res.json();
    expect(body.updated).toBe(2);

    // Verify both are active again
    for (const id of ["LINK-001", "LINK-002"]) {
      const checkRes = await apiContext.get(`/api/links/${id}`);
      const checkBody = await checkRes.json();
      expect(checkBody.status).toBe("active");
    }
  });

  // ── 8. Batch select-all ───────────────────────────────────

  test("POST /api/links/batch/select-all — returns all matching link_ids for a filter", async ({
    apiContext,
  }) => {
    const res = await apiContext.post("/api/links/batch/select-all", {
      data: { family_id: FAMILIES.indebtedness },
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("link_ids");
    expect(Array.isArray(body.link_ids)).toBe(true);

    // "minimal" dataset has 3 indebtedness links: LINK-001, LINK-002, LINK-007
    const indebtednessLinks = MINIMAL_LINKS.filter(
      (l) => l.family_id === FAMILIES.indebtedness,
    );
    expect(body.link_ids.length).toBe(indebtednessLinks.length);

    for (const l of indebtednessLinks) {
      expect(body.link_ids).toContain(l.link_id);
    }
  });
});

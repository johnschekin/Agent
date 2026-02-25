/**
 * Phase 2 E2E: Compound covenant handling.
 *
 * Tests compound covenant policy recognition, dual-family status display,
 * independent evidence requirements, and compound resolution link creation.
 * Uses the "conflicts" seed dataset which includes deliberate multi-family overlaps.
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES } from "../fixtures/seed-data";
import { expectOk, expectValidLink } from "../helpers/link-assertions";

test.describe("Compound Covenants API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("conflicts");
  });

  // ── 1. Compound covenant policy in conflict-policies ───────

  test("Compound covenant policy recognized in conflict-policies", async ({
    apiContext,
  }) => {
    const res = await apiContext.get("/api/links/conflict-policies");
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("policies");
    expect(Array.isArray(body.policies)).toBe(true);

    // Find the compound_covenant policy
    const compoundPolicy = body.policies.find(
      (p: Record<string, unknown>) => p.policy_type === "compound_covenant",
    );
    expect(compoundPolicy).toBeDefined();
    expect(compoundPolicy).toHaveProperty("policy_type");
    expect(compoundPolicy.policy_type).toBe("compound_covenant");
    expect(compoundPolicy).toHaveProperty("description");
    expect(typeof compoundPolicy.description).toBe("string");
  });

  // ── 2. Compound sections show both families ────────────────

  test("Sections with compound_covenant status show both families", async ({
    apiContext,
  }) => {
    // The "conflicts" dataset includes sections mapped to multiple families
    const res = await apiContext.get(
      "/api/links/conflicts?policy_type=compound_covenant",
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("conflicts");
    expect(Array.isArray(body.conflicts)).toBe(true);

    // Each compound conflict should reference at least two families
    for (const conflict of body.conflicts) {
      expect(conflict).toHaveProperty("section_ref");
      expect(conflict).toHaveProperty("family_ids");
      expect(Array.isArray(conflict.family_ids)).toBe(true);
      expect(conflict.family_ids.length).toBeGreaterThanOrEqual(2);

      // The families should be distinct
      const uniqueFamilies = new Set(conflict.family_ids);
      expect(uniqueFamilies.size).toBe(conflict.family_ids.length);
    }
  });

  // ── 3. Independent evidence per family ─────────────────────

  test("Compound section requires independent evidence per family", async ({
    apiContext,
  }) => {
    // Get compound conflicts to find a section with multiple families
    const conflictsRes = await apiContext.get(
      "/api/links/conflicts?policy_type=compound_covenant",
    );
    expectOk(conflictsRes);
    const conflictsBody = await conflictsRes.json();

    // Skip if no compound conflicts exist in seed data
    if (conflictsBody.conflicts.length === 0) {
      return;
    }

    const compound = conflictsBody.conflicts[0];
    const sectionRef = compound.section_ref;

    // Attempt to resolve with evidence for only one family (should fail validation)
    const partialRes = await apiContext.post(
      "/api/links/conflicts/resolve",
      {
        data: {
          section_ref: sectionRef,
          resolution: "compound_covenant",
          evidence: [
            {
              family_id: compound.family_ids[0],
              justification: "Heading matches indebtedness pattern",
            },
            // Deliberately omit evidence for the second family
          ],
        },
      },
    );

    // Should fail: compound resolution requires evidence for each family
    expect(partialRes.status()).toBe(422);

    const errorBody = await partialRes.json();
    expect(errorBody).toHaveProperty("detail");
    expect(typeof errorBody.detail).toBe("string");
  });

  // ── 4. Compound resolution creates links ───────────────────

  test("Compound resolution creates compound_covenant links", async ({
    apiContext,
  }) => {
    // Get compound conflicts
    const conflictsRes = await apiContext.get(
      "/api/links/conflicts?policy_type=compound_covenant",
    );
    expectOk(conflictsRes);
    const conflictsBody = await conflictsRes.json();

    // Skip if no compound conflicts exist in seed data
    if (conflictsBody.conflicts.length === 0) {
      return;
    }

    const compound = conflictsBody.conflicts[0];
    const sectionRef = compound.section_ref;

    // Resolve with evidence for all families
    const evidence = compound.family_ids.map(
      (familyId: string, idx: number) => ({
        family_id: familyId,
        justification: `Independent evidence for family ${idx + 1}: heading and keyword match`,
      }),
    );

    const resolveRes = await apiContext.post(
      "/api/links/conflicts/resolve",
      {
        data: {
          section_ref: sectionRef,
          resolution: "compound_covenant",
          evidence,
        },
      },
    );
    expectOk(resolveRes);

    const resolveBody = await resolveRes.json();
    expect(resolveBody).toHaveProperty("created_links");
    expect(Array.isArray(resolveBody.created_links)).toBe(true);

    // Should create one link per family
    expect(resolveBody.created_links.length).toBe(
      compound.family_ids.length,
    );

    // Each created link should have compound_covenant as its link_role
    for (const link of resolveBody.created_links) {
      expectValidLink(link);
      expect(link).toHaveProperty("link_role");
      expect(link.link_role).toBe("compound_covenant");
    }

    // Verify the created links reference distinct families
    const createdFamilies = resolveBody.created_links.map(
      (l: Record<string, unknown>) => l.family_id,
    );
    const uniqueCreatedFamilies = new Set(createdFamilies);
    expect(uniqueCreatedFamilies.size).toBe(compound.family_ids.length);
  });
});

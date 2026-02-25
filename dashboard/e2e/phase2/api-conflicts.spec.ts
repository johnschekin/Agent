/**
 * Phase 2 API E2E tests: Conflict detection and policy management.
 *
 * Tests sections with multi-family links (conflicts),
 * the conflict policy matrix, and meta-rule overrides.
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk } from "../helpers/link-assertions";

test.describe("Conflicts", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // -----------------------------------------------------------------------
  // 1. GET conflicts lists multi-family sections
  // -----------------------------------------------------------------------
  test("GET conflicts lists multi-family sections", async ({ apiContext }) => {
    // The minimal seed data has DOC-001 with links from indebtedness (7.01),
    // liens (7.02), dividends (7.06), and investments (7.04).
    // These are different sections, so they should not conflict.
    // To create a conflict, we need two families linked to the SAME section.
    // Seed additional links that overlap on the same doc_id + section_number.
    const conflictLinks = [
      {
        family_id: FAMILIES.indebtedness,
        doc_id: "DOC-010",
        section_number: "7.03",
        heading: "Shared Section",
        confidence: 0.85,
        confidence_tier: "high",
        status: "active",
      },
      {
        family_id: FAMILIES.liens,
        doc_id: "DOC-010",
        section_number: "7.03",
        heading: "Shared Section",
        confidence: 0.80,
        confidence_tier: "high",
        status: "active",
      },
      {
        family_id: FAMILIES.dividends,
        doc_id: "DOC-010",
        section_number: "7.03",
        heading: "Shared Section",
        confidence: 0.70,
        confidence_tier: "medium",
        status: "active",
      },
    ];

    // Seed the conflict links directly
    const seedRes = await apiContext.post("/api/links/_test/seed", {
      data: { links: conflictLinks },
    });
    expectOk(seedRes);

    // Now fetch conflicts
    const conflictsRes = await apiContext.get("/api/links/conflicts");
    expectOk(conflictsRes);

    const body = await conflictsRes.json();
    expect(body).toHaveProperty("conflicts");
    expect(body).toHaveProperty("total");
    expect(body.total).toBeGreaterThanOrEqual(1);

    // Find our deliberately created conflict
    const conflict = body.conflicts.find(
      (c: Record<string, unknown>) =>
        c.doc_id === "DOC-010" && c.section_number === "7.03",
    );
    expect(conflict).toBeTruthy();
    expect(conflict.family_count).toBeGreaterThanOrEqual(2);
    expect(conflict.families).toEqual(
      expect.arrayContaining([FAMILIES.indebtedness, FAMILIES.liens]),
    );

    // Each conflict should have policies for each family pair
    expect(conflict).toHaveProperty("policies");
    expect(Array.isArray(conflict.policies)).toBeTruthy();
    expect(conflict.policies.length).toBeGreaterThanOrEqual(1);
    for (const policy of conflict.policies) {
      expect(policy).toHaveProperty("family_a");
      expect(policy).toHaveProperty("family_b");
      expect(policy).toHaveProperty("policy");
    }
  });

  // -----------------------------------------------------------------------
  // 2. GET conflict-policies returns matrix
  // -----------------------------------------------------------------------
  test("GET conflict-policies returns matrix", async ({ apiContext }) => {
    const res = await apiContext.get("/api/links/conflict-policies");
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("policies");
    expect(body).toHaveProperty("total");
    expect(Array.isArray(body.policies)).toBeTruthy();

    // Each policy entry should have family_a, family_b, and a policy value
    for (const policy of body.policies) {
      expect(policy).toHaveProperty("family_a");
      expect(policy).toHaveProperty("family_b");
      expect(typeof policy.family_a).toBe("string");
      expect(typeof policy.family_b).toBe("string");
    }
  });

  // -----------------------------------------------------------------------
  // 3. POST conflict-policies creates meta-rule
  // -----------------------------------------------------------------------
  test("POST conflict-policies creates meta-rule", async ({ apiContext }) => {
    const metaRule = {
      family_a: FAMILIES.indebtedness,
      family_b: FAMILIES.liens,
      policy: "coexist",
      reason: "Indebtedness and liens sections commonly share provisions",
    };

    const createRes = await apiContext.post("/api/links/conflict-policies", {
      data: metaRule,
    });
    expectOk(createRes);
    const createBody = await createRes.json();
    expect(createBody.status).toBe("saved");

    // Verify the policy was persisted by fetching the matrix
    const listRes = await apiContext.get("/api/links/conflict-policies");
    expectOk(listRes);
    const listBody = await listRes.json();

    // Find the policy we just created
    const found = listBody.policies.find(
      (p: Record<string, unknown>) =>
        (p.family_a === FAMILIES.indebtedness &&
          p.family_b === FAMILIES.liens) ||
        (p.family_a === FAMILIES.liens &&
          p.family_b === FAMILIES.indebtedness),
    );
    expect(found).toBeTruthy();
  });

  // -----------------------------------------------------------------------
  // 4. Meta-rule overrides computed policy
  // -----------------------------------------------------------------------
  test("Meta-rule overrides computed policy", async ({ apiContext }) => {
    // First, create conflict data so the conflict endpoint returns results
    const conflictLinks = [
      {
        family_id: FAMILIES.mergers,
        doc_id: "DOC-015",
        section_number: "7.10",
        heading: "Overlap Section",
        confidence: 0.80,
        confidence_tier: "high",
        status: "active",
      },
      {
        family_id: FAMILIES.asset_sales,
        doc_id: "DOC-015",
        section_number: "7.10",
        heading: "Overlap Section",
        confidence: 0.75,
        confidence_tier: "medium",
        status: "active",
      },
    ];
    const seedRes = await apiContext.post("/api/links/_test/seed", {
      data: { links: conflictLinks },
    });
    expectOk(seedRes);

    // Get conflicts before override
    const beforeRes = await apiContext.get("/api/links/conflicts");
    expectOk(beforeRes);
    const beforeBody = await beforeRes.json();
    const conflictBefore = beforeBody.conflicts.find(
      (c: Record<string, unknown>) =>
        c.doc_id === "DOC-015" && c.section_number === "7.10",
    );
    expect(conflictBefore).toBeTruthy();

    // Record the original policy for the mergers/asset_sales pair
    const originalPolicy = conflictBefore.policies.find(
      (p: Record<string, unknown>) =>
        (p.family_a === FAMILIES.mergers &&
          p.family_b === FAMILIES.asset_sales) ||
        (p.family_a === FAMILIES.asset_sales &&
          p.family_b === FAMILIES.mergers),
    );

    // Create a meta-rule override with a specific policy
    const overridePolicy = "exclusive";
    const overrideRes = await apiContext.post("/api/links/conflict-policies", {
      data: {
        family_a: FAMILIES.mergers,
        family_b: FAMILIES.asset_sales,
        policy: overridePolicy,
        reason: "Admin override: mergers and asset sales are mutually exclusive",
      },
    });
    expectOk(overrideRes);

    // Verify the override is reflected in conflict-policies GET
    const afterPoliciesRes = await apiContext.get(
      "/api/links/conflict-policies",
    );
    expectOk(afterPoliciesRes);
    const afterPoliciesBody = await afterPoliciesRes.json();

    const overriddenPolicy = afterPoliciesBody.policies.find(
      (p: Record<string, unknown>) =>
        (p.family_a === FAMILIES.mergers &&
          p.family_b === FAMILIES.asset_sales) ||
        (p.family_a === FAMILIES.asset_sales &&
          p.family_b === FAMILIES.mergers),
    );
    expect(overriddenPolicy).toBeTruthy();
    expect(overriddenPolicy.policy).toBe(overridePolicy);

    // If there was an original computed policy, it should now be overridden
    if (originalPolicy) {
      expect(overriddenPolicy.policy).not.toBe(originalPolicy.policy);
    }
  });
});

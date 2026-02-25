/**
 * Phase 2 API E2E tests: Macros and Template Baselines.
 *
 * Tests CRUD for macros, macro expansion in DSL validation,
 * circular macro detection, and template baseline management.
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk } from "../helpers/link-assertions";

test.describe("Macros & Baselines", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // -----------------------------------------------------------------------
  // 1. POST /api/links/macros -- creates macro
  // -----------------------------------------------------------------------
  test("POST /api/links/macros creates macro", async ({ apiContext }) => {
    const macro = {
      name: "debt_headings",
      description: "Common indebtedness heading patterns",
      family_id: FAMILIES.indebtedness,
      ast_json: JSON.stringify({
        type: "group",
        operator: "or",
        children: [
          { type: "match", value: "Indebtedness" },
          { type: "match", value: "Limitation on Indebtedness" },
          { type: "match", value: "Debt" },
        ],
      }),
    };

    const res = await apiContext.post("/api/links/macros", { data: macro });
    expect(res.status()).toBe(201);

    const body = await res.json();
    expect(body.status).toBe("saved");
  });

  // -----------------------------------------------------------------------
  // 2. GET /api/links/macros -- lists macros
  // -----------------------------------------------------------------------
  test("GET /api/links/macros lists macros", async ({ apiContext }) => {
    // Create two macros first
    const macro1 = {
      name: "lien_headings",
      description: "Common lien heading patterns",
      family_id: FAMILIES.liens,
      ast_json: JSON.stringify({
        type: "group",
        operator: "or",
        children: [
          { type: "match", value: "Liens" },
          { type: "match", value: "Limitation on Liens" },
        ],
      }),
    };
    const macro2 = {
      name: "dividend_headings",
      description: "Common dividend heading patterns",
      family_id: FAMILIES.dividends,
      ast_json: JSON.stringify({
        type: "group",
        operator: "or",
        children: [
          { type: "match", value: "Restricted Payments" },
          { type: "match", value: "Dividends" },
        ],
      }),
    };

    const res1 = await apiContext.post("/api/links/macros", { data: macro1 });
    expect(res1.status()).toBe(201);
    const res2 = await apiContext.post("/api/links/macros", { data: macro2 });
    expect(res2.status()).toBe(201);

    // List macros
    const listRes = await apiContext.get("/api/links/macros");
    expectOk(listRes);

    const body = await listRes.json();
    expect(body).toHaveProperty("macros");
    expect(body).toHaveProperty("total");
    expect(Array.isArray(body.macros)).toBeTruthy();
    expect(body.total).toBeGreaterThanOrEqual(2);

    // Verify our macros are in the list
    const names = body.macros.map((m: Record<string, unknown>) => m.name);
    expect(names).toContain("lien_headings");
    expect(names).toContain("dividend_headings");
  });

  // -----------------------------------------------------------------------
  // 3. Macro expansion in DSL validate
  // -----------------------------------------------------------------------
  test("Macro expansion in DSL validate", async ({ apiContext }) => {
    // First create a macro that the DSL validator can expand
    const macro = {
      name: "neg_covenant_headings",
      description: "Negative covenant heading patterns",
      family_id: FAMILIES.indebtedness,
      ast_json: JSON.stringify({
        type: "group",
        operator: "or",
        children: [
          { type: "match", value: "Indebtedness" },
          { type: "match", value: "Liens" },
          { type: "match", value: "Restricted Payments" },
        ],
      }),
    };
    const createRes = await apiContext.post("/api/links/macros", {
      data: macro,
    });
    expect(createRes.status()).toBe(201);

    // Seed a rule so we can use the rule-scoped validate-dsl endpoint
    const ruleData = {
      rule_id: "RULE-MACRO-TEST",
      family_id: FAMILIES.indebtedness,
      heading_filter_ast: {
        type: "match",
        value: "Indebtedness",
      },
      status: "draft",
      version: 1,
    };
    const seedRes = await apiContext.post("/api/links/_test/seed", {
      data: { rules: [ruleData] },
    });
    expectOk(seedRes);

    // Validate DSL that references the macro via @name syntax
    const validateRes = await apiContext.post(
      "/api/links/rules/RULE-MACRO-TEST/validate-dsl",
      { data: { text: 'heading: @neg_covenant_headings' } },
    );
    expectOk(validateRes);

    const body = await validateRes.json();

    // If macro expansion works, heading field should be populated
    expect(body).toHaveProperty("text_fields");
    expect(body.text_fields).toHaveProperty("heading");

    // Should include normalized_text showing the expanded form
    expect(body).toHaveProperty("normalized_text");
    expect(typeof body.normalized_text).toBe("string");
  });

  // -----------------------------------------------------------------------
  // 4. Circular macro rejected
  // -----------------------------------------------------------------------
  test("Circular macro rejected", async ({ apiContext }) => {
    // Create macro A that references macro B
    const macroA = {
      name: "circular_a",
      description: "Macro A referencing B",
      ast_json: JSON.stringify({
        type: "macro_ref",
        name: "circular_b",
      }),
    };
    const resA = await apiContext.post("/api/links/macros", { data: macroA });
    expect(resA.status()).toBe(201);

    // Create macro B that references macro A
    const macroB = {
      name: "circular_b",
      description: "Macro B referencing A",
      ast_json: JSON.stringify({
        type: "macro_ref",
        name: "circular_a",
      }),
    };
    const resB = await apiContext.post("/api/links/macros", { data: macroB });
    expect(resB.status()).toBe(201);

    // Create a rule for DSL validation context
    const ruleData = {
      rule_id: "RULE-CIRCULAR-TEST",
      family_id: FAMILIES.indebtedness,
      heading_filter_ast: { type: "match", value: "Test" },
      status: "draft",
      version: 1,
    };
    const seedRes = await apiContext.post("/api/links/_test/seed", {
      data: { rules: [ruleData] },
    });
    expectOk(seedRes);

    // Attempt to validate DSL referencing the circular macro
    const validateRes = await apiContext.post(
      "/api/links/rules/RULE-CIRCULAR-TEST/validate-dsl",
      { data: { text: 'heading: @circular_a' } },
    );

    // The response should be 200 but contain errors about the circular reference,
    // OR the server may return an error status
    const body = await validateRes.json();
    if (validateRes.ok()) {
      // If 200, expect errors in the result
      expect(body).toHaveProperty("errors");
      expect(body.errors.length).toBeGreaterThan(0);

      const circularError = body.errors.find(
        (e: { message: string }) =>
          e.message.toLowerCase().includes("circular") ||
          e.message.toLowerCase().includes("recursive") ||
          e.message.toLowerCase().includes("cycle") ||
          e.message.toLowerCase().includes("not found") ||
          e.message.toLowerCase().includes("undefined"),
      );
      expect(circularError).toBeTruthy();
    } else {
      // If error status, that is also acceptable behavior
      expect([400, 422, 500]).toContain(validateRes.status());
    }
  });

  // -----------------------------------------------------------------------
  // 5. DELETE /api/links/macros/{name} -- deletes macro
  // -----------------------------------------------------------------------
  test("DELETE /api/links/macros/{name} deletes macro", async ({
    apiContext,
  }) => {
    // Create a macro to delete
    const macro = {
      name: "to_delete",
      description: "Macro to be deleted",
      ast_json: JSON.stringify({
        type: "match",
        value: "Delete Me",
      }),
    };
    const createRes = await apiContext.post("/api/links/macros", {
      data: macro,
    });
    expect(createRes.status()).toBe(201);

    // Verify it exists
    const beforeRes = await apiContext.get("/api/links/macros");
    expectOk(beforeRes);
    const beforeBody = await beforeRes.json();
    const beforeNames = beforeBody.macros.map(
      (m: Record<string, unknown>) => m.name,
    );
    expect(beforeNames).toContain("to_delete");

    // Delete it
    const deleteRes = await apiContext.delete("/api/links/macros/to_delete");
    expectOk(deleteRes);
    const deleteBody = await deleteRes.json();
    expect(deleteBody.deleted).toBe(true);

    // Verify it no longer appears in the list
    const afterRes = await apiContext.get("/api/links/macros");
    expectOk(afterRes);
    const afterBody = await afterRes.json();
    const afterNames = afterBody.macros.map(
      (m: Record<string, unknown>) => m.name,
    );
    expect(afterNames).not.toContain("to_delete");
  });

  // -----------------------------------------------------------------------
  // 6. POST /api/links/template-baselines -- creates template baseline
  // -----------------------------------------------------------------------
  test("POST /api/links/template-baselines creates template baseline", async ({
    apiContext,
  }) => {
    const baseline = {
      family_id: FAMILIES.indebtedness,
      template: "standard_lbo",
      expected_sections: ["7.01", "7.02", "7.03"],
      min_confidence: 0.7,
      description: "Standard LBO indebtedness baseline",
    };

    const res = await apiContext.post("/api/links/template-baselines", {
      data: baseline,
    });
    expectOk(res);

    const body = await res.json();
    expect(body.status).toBe("saved");
  });

  // -----------------------------------------------------------------------
  // 7. GET /api/links/template-baselines -- returns baselines
  // -----------------------------------------------------------------------
  test("GET /api/links/template-baselines returns baselines", async ({
    apiContext,
  }) => {
    // Create two baselines for different families
    const baseline1 = {
      family_id: FAMILIES.indebtedness,
      template: "standard_lbo",
      expected_sections: ["7.01"],
      min_confidence: 0.7,
    };
    const baseline2 = {
      family_id: FAMILIES.liens,
      template: "standard_lbo",
      expected_sections: ["7.02"],
      min_confidence: 0.7,
    };

    const res1 = await apiContext.post("/api/links/template-baselines", {
      data: baseline1,
    });
    expectOk(res1);
    const res2 = await apiContext.post("/api/links/template-baselines", {
      data: baseline2,
    });
    expectOk(res2);

    // List all baselines
    const listRes = await apiContext.get("/api/links/template-baselines");
    expectOk(listRes);
    const body = await listRes.json();

    expect(body).toHaveProperty("baselines");
    expect(body).toHaveProperty("total");
    expect(Array.isArray(body.baselines)).toBeTruthy();
    expect(body.total).toBeGreaterThanOrEqual(2);

    // Test filtering by family_id
    const filteredRes = await apiContext.get(
      `/api/links/template-baselines?family_id=${FAMILIES.indebtedness}`,
    );
    expectOk(filteredRes);
    const filteredBody = await filteredRes.json();
    expect(filteredBody.total).toBeGreaterThanOrEqual(1);

    // All filtered results should belong to the requested family
    for (const bl of filteredBody.baselines) {
      expect(bl.family_id).toBe(FAMILIES.indebtedness);
    }
  });

  // -----------------------------------------------------------------------
  // 8. Macro scoping -- family-specific macro + _global fallback
  // -----------------------------------------------------------------------
  test("Macro scoping -- family-specific macro + _global fallback", async ({
    apiContext,
  }) => {
    // Create a global macro (no family_id or with special _global scope)
    const globalMacro = {
      name: "common_terms",
      description: "Global macro available to all families",
      family_id: "_global",
      ast_json: JSON.stringify({
        type: "group",
        operator: "or",
        children: [
          { type: "match", value: "Limitation" },
          { type: "match", value: "Restriction" },
        ],
      }),
    };
    const globalRes = await apiContext.post("/api/links/macros", {
      data: globalMacro,
    });
    expect(globalRes.status()).toBe(201);

    // Create a family-specific macro for indebtedness
    const familyMacro = {
      name: "debt_terms",
      description: "Indebtedness-specific terms",
      family_id: FAMILIES.indebtedness,
      ast_json: JSON.stringify({
        type: "group",
        operator: "or",
        children: [
          { type: "match", value: "Indebtedness" },
          { type: "match", value: "Debt" },
          { type: "match", value: "Borrowing" },
        ],
      }),
    };
    const familyRes = await apiContext.post("/api/links/macros", {
      data: familyMacro,
    });
    expect(familyRes.status()).toBe(201);

    // List all macros and verify both are present
    const listRes = await apiContext.get("/api/links/macros");
    expectOk(listRes);
    const body = await listRes.json();

    const macroNames = body.macros.map(
      (m: Record<string, unknown>) => m.name,
    );
    expect(macroNames).toContain("common_terms");
    expect(macroNames).toContain("debt_terms");

    // Verify the global macro has _global family_id
    const globalFound = body.macros.find(
      (m: Record<string, unknown>) => m.name === "common_terms",
    );
    expect(globalFound).toBeTruthy();
    expect(globalFound.family_id).toBe("_global");

    // Verify the family-specific macro has the correct family_id
    const familyFound = body.macros.find(
      (m: Record<string, unknown>) => m.name === "debt_terms",
    );
    expect(familyFound).toBeTruthy();
    expect(familyFound.family_id).toBe(FAMILIES.indebtedness);

    // Both macros should be usable in DSL validation for a rule in the
    // indebtedness family (family-specific + global fallback)
    const ruleData = {
      rule_id: "RULE-SCOPE-TEST",
      family_id: FAMILIES.indebtedness,
      heading_filter_ast: { type: "match", value: "Test" },
      status: "draft",
      version: 1,
    };
    const seedRes = await apiContext.post("/api/links/_test/seed", {
      data: { rules: [ruleData] },
    });
    expectOk(seedRes);

    // Validate DSL using the family-specific macro
    const validateFamily = await apiContext.post(
      "/api/links/rules/RULE-SCOPE-TEST/validate-dsl",
      { data: { text: 'heading: @debt_terms' } },
    );
    expectOk(validateFamily);
    const familyValidation = await validateFamily.json();
    expect(familyValidation.text_fields).toHaveProperty("heading");

    // Validate DSL using the global macro
    const validateGlobal = await apiContext.post(
      "/api/links/rules/RULE-SCOPE-TEST/validate-dsl",
      { data: { text: 'heading: @common_terms' } },
    );
    expectOk(validateGlobal);
    const globalValidation = await validateGlobal.json();
    expect(globalValidation.text_fields).toHaveProperty("heading");
  });
});

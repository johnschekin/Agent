/**
 * Phase 2 API E2E tests: DSL validation endpoint.
 *
 * Tests the DSL parser/validator including:
 * - Valid DSL returning AST + normalized_text
 * - Invalid DSL returning errors
 * - Proximity on allowed vs disallowed fields
 * - Query cost estimation
 * - Guardrail rejection of pathological queries
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk } from "../helpers/link-assertions";

test.describe("DSL Validation", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // -----------------------------------------------------------------------
  // 1. Valid DSL returns AST + normalized_text
  // -----------------------------------------------------------------------
  test("Valid DSL returns AST + normalized_text", async ({ apiContext }) => {
    const res = await apiContext.post("/api/links/rules/validate-dsl-standalone", {
      data: {
        text: 'heading: "Indebtedness" | "Limitation on Indebtedness"',
      },
    });
    expectOk(res);

    const body = await res.json();

    // Should have text_fields with parsed heading expression
    expect(body).toHaveProperty("text_fields");
    expect(body.text_fields).toHaveProperty("heading");

    // The heading AST should be a group (OR) or match node
    const headingAst = body.text_fields.heading;
    expect(headingAst).toBeTruthy();

    // Should return normalized_text
    expect(body).toHaveProperty("normalized_text");
    expect(typeof body.normalized_text).toBe("string");
    expect(body.normalized_text.length).toBeGreaterThan(0);

    // Should have no errors
    expect(body).toHaveProperty("errors");
    expect(body.errors).toHaveLength(0);

    // Should include query_cost
    expect(body).toHaveProperty("query_cost");
    expect(typeof body.query_cost).toBe("number");
  });

  // -----------------------------------------------------------------------
  // 2. Invalid DSL returns errors array
  // -----------------------------------------------------------------------
  test("Invalid DSL returns errors array", async ({ apiContext }) => {
    const res = await apiContext.post("/api/links/rules/validate-dsl-standalone", {
      data: {
        text: '@@@ invalid %%% broken DSL !!!',
      },
    });
    expectOk(res);

    const body = await res.json();

    // Should have errors
    expect(body).toHaveProperty("errors");
    expect(body.errors.length).toBeGreaterThan(0);

    // Each error should have message and position
    for (const err of body.errors) {
      expect(err).toHaveProperty("message");
      expect(typeof err.message).toBe("string");
      expect(err).toHaveProperty("position");
      expect(typeof err.position).toBe("number");
    }
  });

  // -----------------------------------------------------------------------
  // 3. Proximity on clause field accepted
  // -----------------------------------------------------------------------
  test("Proximity on clause field accepted", async ({ apiContext }) => {
    // DSL syntax: clause: "indebted" /5 "permitted"
    // Proximity operator /5 means within 5 words
    const res = await apiContext.post("/api/links/rules/validate-dsl-standalone", {
      data: {
        text: 'clause: "indebted" /5 "permitted"',
      },
    });
    expectOk(res);

    const body = await res.json();

    // Should have no errors — proximity is valid on clause field
    expect(body.errors).toHaveLength(0);

    // Should have parsed clause field
    expect(body.text_fields).toHaveProperty("clause");
    const clauseAst = body.text_fields.clause;
    expect(clauseAst).toBeTruthy();

    // Query cost should be elevated for proximity queries
    expect(body.query_cost).toBeGreaterThan(0);
  });

  // -----------------------------------------------------------------------
  // 4. Proximity on heading field rejected
  // -----------------------------------------------------------------------
  test("Proximity on heading field rejected", async ({ apiContext }) => {
    // Proximity operators are only allowed on clause field, not heading
    const res = await apiContext.post("/api/links/rules/validate-dsl-standalone", {
      data: {
        text: 'heading: "Indebtedness" /5 "Limitation"',
      },
    });
    expectOk(res);

    const body = await res.json();

    // Should have at least one error about proximity not being valid on heading
    expect(body.errors.length).toBeGreaterThan(0);

    const proximityError = body.errors.find(
      (e: { message: string }) =>
        e.message.toLowerCase().includes("proximity") ||
        e.message.toLowerCase().includes("only valid on clause"),
    );
    expect(proximityError).toBeTruthy();
  });

  // -----------------------------------------------------------------------
  // 5. Query cost returned
  // -----------------------------------------------------------------------
  test("Query cost returned", async ({ apiContext }) => {
    // Simple query should have low cost
    const simpleRes = await apiContext.post(
      "/api/links/rules/validate-dsl-standalone",
      { data: { text: 'heading: "Indebtedness"' } },
    );
    expectOk(simpleRes);
    const simpleBody = await simpleRes.json();
    expect(simpleBody).toHaveProperty("query_cost");
    expect(typeof simpleBody.query_cost).toBe("number");
    expect(simpleBody.query_cost).toBeGreaterThanOrEqual(0);
    const simpleCost = simpleBody.query_cost as number;

    // Complex query should have higher cost
    const complexRes = await apiContext.post(
      "/api/links/rules/validate-dsl-standalone",
      {
        data: {
          text:
            'heading: "Indebtedness" | "Liens" | "Dividends" | "Restricted Payments" ' +
            'clause: "permitted" | "exception" | "basket" | "limitation"',
        },
      },
    );
    expectOk(complexRes);
    const complexBody = await complexRes.json();
    expect(complexBody).toHaveProperty("query_cost");
    expect(typeof complexBody.query_cost).toBe("number");
    const complexCost = complexBody.query_cost as number;

    // Complex query should cost more than simple query
    expect(complexCost).toBeGreaterThan(simpleCost);
  });

  // -----------------------------------------------------------------------
  // 6. Guardrail rejects pathological query
  // -----------------------------------------------------------------------
  test("Guardrail rejects pathological query", async ({ apiContext }) => {
    // Build a deeply nested OR expression that exceeds MAX_QUERY_COST (100)
    // or MAX_AST_DEPTH (5) or MAX_AST_NODES (50)
    // Generate many OR branches to exceed cost/node limits
    const manyTerms = Array.from(
      { length: 60 },
      (_, i) => `"term_${i}"`,
    ).join(" | ");

    const res = await apiContext.post(
      "/api/links/rules/validate-dsl-standalone",
      {
        data: {
          text: `heading: ${manyTerms}`,
        },
      },
    );
    expectOk(res);

    const body = await res.json();

    // Should have guardrail errors (cost exceeded, node count exceeded, etc.)
    expect(body.errors.length).toBeGreaterThan(0);

    // At least one error should mention cost, depth, node count, or wildcard
    const guardrailError = body.errors.find(
      (e: { message: string }) =>
        e.message.toLowerCase().includes("cost") ||
        e.message.toLowerCase().includes("depth") ||
        e.message.toLowerCase().includes("node") ||
        e.message.toLowerCase().includes("wildcard") ||
        e.message.toLowerCase().includes("exceed") ||
        e.message.toLowerCase().includes("maximum"),
    );
    expect(guardrailError).toBeTruthy();
  });
});

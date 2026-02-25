/**
 * Phase 2 E2E: Cognitive helpers — crossref peek, rule evaluation, and counterfactual coverage.
 *
 * Tests the read-only cognitive endpoints that support reviewer decision-making:
 * cross-reference text preview, rule traffic-light evaluation, and
 * counterfactual coverage analysis.
 * All tests use the deterministic "minimal" seed dataset (10 links, 3 families).
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk } from "../helpers/link-assertions";

test.describe("Cognitive Helpers API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // ── 1. Crossref peek ───────────────────────────────────────

  test("GET /api/links/crossref-peek returns section text", async ({
    apiContext,
  }) => {
    // Use a section reference from the seed data (DOC-001, section 7.01)
    const sectionRef = `${MINIMAL_LINKS[0].doc_id}:${MINIMAL_LINKS[0].section_number}`;

    const res = await apiContext.get(
      `/api/links/crossref-peek?section_ref=${encodeURIComponent(sectionRef)}`,
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("section_ref");
    expect(body.section_ref).toBe(sectionRef);
    expect(body).toHaveProperty("text");
    expect(typeof body.text).toBe("string");
    expect(body.text.length).toBeGreaterThan(0);

    // Should also include metadata about the section
    expect(body).toHaveProperty("heading");
    expect(typeof body.heading).toBe("string");
  });

  // ── 2. Rule evaluate-text — matched ────────────────────────

  test("POST /api/links/rules/evaluate-text returns traffic-light result", async ({
    apiContext,
  }) => {
    // Use the published indebtedness rule (RULE-001)
    const ruleAst = RULES[0].heading_filter_ast;

    const res = await apiContext.post("/api/links/rules/evaluate-text", {
      data: {
        heading_filter_ast: ruleAst,
        text: "Section 7.01 — Limitation on Indebtedness. The Borrower shall not incur any Indebtedness...",
        heading: "Limitation on Indebtedness",
      },
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("matched");
    expect(body.matched).toBe(true);
    expect(body).toHaveProperty("traffic_light");
    expect(["green", "yellow", "red"]).toContain(body.traffic_light);

    // For a strong match, traffic light should be green
    expect(body.traffic_light).toBe("green");

    // Should include which rule nodes matched
    expect(body).toHaveProperty("matched_nodes");
    expect(Array.isArray(body.matched_nodes)).toBe(true);
    expect(body.matched_nodes.length).toBeGreaterThan(0);
  });

  // ── 3. Counterfactual coverage ─────────────────────────────

  test("POST /api/links/coverage/counterfactual returns new_hits + fps", async ({
    apiContext,
  }) => {
    // Test counterfactual: "What if we added 'Debt' as a heading match?"
    const counterfactualRule = {
      family_id: FAMILIES.indebtedness,
      heading_filter_ast: {
        type: "group",
        operator: "or",
        children: [
          { type: "match", value: "Indebtedness" },
          { type: "match", value: "Limitation on Indebtedness" },
          { type: "match", value: "Debt" },
          { type: "match", value: "Debt Limitations" },
        ],
      },
    };

    const res = await apiContext.post(
      "/api/links/coverage/counterfactual",
      { data: counterfactualRule },
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("new_hits");
    expect(typeof body.new_hits).toBe("number");
    expect(body.new_hits).toBeGreaterThanOrEqual(0);

    expect(body).toHaveProperty("false_positives");
    expect(typeof body.false_positives).toBe("number");
    expect(body.false_positives).toBeGreaterThanOrEqual(0);

    // Should also return the total matched count for context
    expect(body).toHaveProperty("total_matched");
    expect(typeof body.total_matched).toBe("number");
  });

  // ── 4. evaluate-text with unmatched rule ───────────────────

  test("evaluate-text with unmatched rule returns matched=false", async ({
    apiContext,
  }) => {
    // Use a rule that should NOT match the provided text
    const ruleAst = {
      type: "group",
      operator: "or",
      children: [
        { type: "match", value: "Restricted Payments" },
        { type: "match", value: "Dividends" },
      ],
    };

    const res = await apiContext.post("/api/links/rules/evaluate-text", {
      data: {
        heading_filter_ast: ruleAst,
        text: "Section 7.01 — Limitation on Indebtedness. The Borrower shall not incur any Indebtedness...",
        heading: "Limitation on Indebtedness",
      },
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("matched");
    expect(body.matched).toBe(false);
    expect(body).toHaveProperty("traffic_light");
    expect(body.traffic_light).toBe("red");

    // No nodes should have matched
    expect(body).toHaveProperty("matched_nodes");
    expect(Array.isArray(body.matched_nodes)).toBe(true);
    expect(body.matched_nodes.length).toBe(0);
  });

  // ── 5. Crossref peek with invalid section ref ─────────────

  test("crossref-peek returns 404 for invalid section_ref", async ({
    apiContext,
  }) => {
    const invalidRef = "DOC-NONEXISTENT:99.99";

    const res = await apiContext.get(
      `/api/links/crossref-peek?section_ref=${encodeURIComponent(invalidRef)}`,
    );

    expect(res.status()).toBe(404);

    const body = await res.json();
    expect(body).toHaveProperty("detail");
    expect(typeof body.detail).toBe("string");
  });
});

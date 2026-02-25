/**
 * Phase 2 E2E: Embeddings, centroids, starter kits, and comparables.
 *
 * Tests embedding computation, similarity search, centroid recomputation,
 * starter-kit retrieval/generation, rule-draft scaffolding, comparables,
 * and meta-field DSL validation.
 * All tests use the deterministic "minimal" seed dataset (10 links, 3 families).
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk } from "../helpers/link-assertions";
import { waitForJob } from "../helpers/wait-for-job";

test.describe("Embeddings & Starter Kits API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // ── 1. Compute embeddings job ──────────────────────────────

  test("POST /api/links/embeddings/compute submits job", async ({
    apiContext,
  }) => {
    const res = await apiContext.post("/api/links/embeddings/compute", {
      data: {
        link_ids: ["LINK-001", "LINK-002", "LINK-003"],
      },
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("job_id");
    expect(typeof body.job_id).toBe("string");
    expect(body.job_id.length).toBeGreaterThan(0);

    // Wait for the embedding computation to finish
    const job = await waitForJob(apiContext, body.job_id, {
      timeoutMs: 30_000,
    });
    expect(job.status).toBe("completed");
  });

  // ── 2. Similar links via embeddings ────────────────────────

  test("GET /api/links/embeddings/similar returns top-K", async ({
    apiContext,
  }) => {
    // First compute embeddings so similarity can work
    const computeRes = await apiContext.post(
      "/api/links/embeddings/compute",
      {
        data: {
          link_ids: MINIMAL_LINKS.map((l) => l.link_id),
        },
      },
    );
    expectOk(computeRes);
    const { job_id } = await computeRes.json();
    await waitForJob(apiContext, job_id, { timeoutMs: 30_000 });

    // Query similar links for LINK-001
    const res = await apiContext.get(
      "/api/links/embeddings/similar?link_id=LINK-001&top_k=5",
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("similar");
    expect(Array.isArray(body.similar)).toBe(true);
    expect(body.similar.length).toBeLessThanOrEqual(5);

    // Each result should have link_id and similarity score
    for (const item of body.similar) {
      expect(item).toHaveProperty("link_id");
      expect(item).toHaveProperty("similarity");
      expect(typeof item.similarity).toBe("number");
      expect(item.similarity).toBeGreaterThanOrEqual(0);
      expect(item.similarity).toBeLessThanOrEqual(1);
    }

    // The query link should not appear in its own results
    const resultIds = body.similar.map(
      (s: Record<string, unknown>) => s.link_id,
    );
    expect(resultIds).not.toContain("LINK-001");
  });

  // ── 3. Recompute centroid ──────────────────────────────────

  test("POST /api/links/centroids/recompute updates centroid", async ({
    apiContext,
  }) => {
    // First compute embeddings
    const computeRes = await apiContext.post(
      "/api/links/embeddings/compute",
      {
        data: {
          link_ids: MINIMAL_LINKS.map((l) => l.link_id),
        },
      },
    );
    expectOk(computeRes);
    const { job_id } = await computeRes.json();
    await waitForJob(apiContext, job_id, { timeoutMs: 30_000 });

    // Recompute centroid for a family
    const res = await apiContext.post("/api/links/centroids/recompute", {
      data: { family_id: FAMILIES.indebtedness },
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("family_id");
    expect(body.family_id).toBe(FAMILIES.indebtedness);
    expect(body).toHaveProperty("centroid");
    expect(body).toHaveProperty("num_links");
    expect(typeof body.num_links).toBe("number");
    expect(body.num_links).toBeGreaterThan(0);
  });

  // ── 4. Get starter kit ─────────────────────────────────────

  test("GET /api/links/starter-kit/{family_id} returns kit data", async ({
    apiContext,
  }) => {
    const familyId = FAMILIES.indebtedness;

    const res = await apiContext.get(
      `/api/links/starter-kit/${familyId}`,
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("family_id");
    expect(body.family_id).toBe(familyId);
    expect(body).toHaveProperty("headings");
    expect(Array.isArray(body.headings)).toBe(true);
    expect(body).toHaveProperty("keywords");
    expect(Array.isArray(body.keywords)).toBe(true);
    expect(body).toHaveProperty("section_patterns");
    expect(Array.isArray(body.section_patterns)).toBe(true);
  });

  // ── 5. Generate starter kit from corpus ────────────────────

  test("POST /api/links/starter-kit/generate creates from corpus", async ({
    apiContext,
  }) => {
    const res = await apiContext.post("/api/links/starter-kit/generate", {
      data: { family_id: FAMILIES.liens },
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("family_id");
    expect(body.family_id).toBe(FAMILIES.liens);
    expect(body).toHaveProperty("headings");
    expect(Array.isArray(body.headings)).toBe(true);
    expect(body).toHaveProperty("keywords");
    expect(Array.isArray(body.keywords)).toBe(true);

    // Generated kit should have at least some content
    expect(
      body.headings.length + body.keywords.length,
    ).toBeGreaterThan(0);
  });

  // ── 6. Generate rule draft from starter kit ────────────────

  test("POST /api/links/starter-kit/{family_id}/generate-rule-draft returns scaffolded rule", async ({
    apiContext,
  }) => {
    const familyId = FAMILIES.indebtedness;

    const res = await apiContext.post(
      `/api/links/starter-kit/${familyId}/generate-rule-draft`,
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("rule_draft");

    const draft = body.rule_draft;
    expect(draft).toHaveProperty("family_id");
    expect(draft.family_id).toBe(familyId);
    expect(draft).toHaveProperty("heading_filter_ast");
    expect(draft.heading_filter_ast).toHaveProperty("type");
    expect(draft).toHaveProperty("status");
    expect(draft.status).toBe("draft");
  });

  // ── 7. Comparables ─────────────────────────────────────────

  test("GET /api/links/{id}/comparables returns 3-5 sections", async ({
    apiContext,
  }) => {
    const linkId = "LINK-001";

    const res = await apiContext.get(`/api/links/${linkId}/comparables`);
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("comparables");
    expect(Array.isArray(body.comparables)).toBe(true);
    expect(body.comparables.length).toBeGreaterThanOrEqual(1);
    expect(body.comparables.length).toBeLessThanOrEqual(5);

    // Each comparable should have section info and a similarity metric
    for (const comp of body.comparables) {
      expect(comp).toHaveProperty("doc_id");
      expect(comp).toHaveProperty("section_number");
      expect(comp).toHaveProperty("heading");
      expect(comp).toHaveProperty("similarity");
      expect(typeof comp.similarity).toBe("number");
    }
  });

  // ── 8. Meta-field DSL validate ─────────────────────────────

  test("Meta-field DSL validate returns correct AST", async ({
    apiContext,
  }) => {
    const dslExpression = 'heading MATCHES "Indebtedness" OR heading MATCHES "Debt"';

    const res = await apiContext.post("/api/links/dsl/validate", {
      data: { expression: dslExpression },
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("valid");
    expect(body.valid).toBe(true);
    expect(body).toHaveProperty("ast");

    // Verify the AST structure
    const ast = body.ast;
    expect(ast).toHaveProperty("type");
    expect(ast.type).toBe("group");
    expect(ast).toHaveProperty("operator");
    expect(ast.operator).toBe("or");
    expect(ast).toHaveProperty("children");
    expect(Array.isArray(ast.children)).toBe(true);
    expect(ast.children.length).toBe(2);

    // Each child should be a match node
    for (const child of ast.children) {
      expect(child.type).toBe("match");
      expect(child).toHaveProperty("field");
      expect(child.field).toBe("heading");
      expect(child).toHaveProperty("value");
      expect(typeof child.value).toBe("string");
    }
  });
});

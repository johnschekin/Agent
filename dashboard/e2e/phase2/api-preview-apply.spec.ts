/**
 * Phase 2 E2E: Preview + Apply workflow.
 *
 * Tests the full preview lifecycle: create preview (sync/async),
 * paginate candidates, set verdicts, apply accepted links, and
 * reject stale/mismatched previews.
 */
import { test, expect } from "../fixtures/links-db";
import { FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk, expectPaginated } from "../helpers/link-assertions";
import { waitForJob } from "../helpers/wait-for-job";

test.describe("Preview & Apply API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // ── 1. POST /api/links/preview (sync) ────────────────────

  test("POST /api/links/preview (sync) — creates preview with candidates", async ({
    apiContext,
  }) => {
    const res = await apiContext.post("/api/links/preview", {
      data: {
        family_id: FAMILIES.indebtedness,
        rule_id: RULES[0].rule_id,
        doc_ids: ["DOC-001", "DOC-002", "DOC-005"],
      },
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("preview_id");
    expect(body).toHaveProperty("status");
    expect(body).toHaveProperty("candidates");
    expect(body).toHaveProperty("family_id", FAMILIES.indebtedness);
    expect(body).toHaveProperty("content_hash");
    expect(typeof body.content_hash).toBe("string");
    expect(body.content_hash.length).toBeGreaterThan(0);

    // Candidates is an array (may be populated or empty depending on matching)
    expect(Array.isArray(body.candidates)).toBe(true);
  });

  // ── 2. POST /api/links/preview (async via job) ───────────

  test("POST /api/links/preview (async via job) — returns job_id for large sets", async ({
    apiContext,
  }) => {
    // Use a large doc_ids array to trigger async processing
    const manyDocIds = Array.from({ length: 100 }, (_, i) =>
      `DOC-${String(i + 1).padStart(3, "0")}`,
    );

    const res = await apiContext.post("/api/links/preview", {
      data: {
        family_id: FAMILIES.liens,
        rule_id: RULES[1].rule_id, // RULE-002, liens
        doc_ids: manyDocIds,
        async: true,
      },
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("job_id");
    expect(typeof body.job_id).toBe("string");

    // Wait for the job to complete
    const job = await waitForJob(apiContext, body.job_id, {
      timeoutMs: 30_000,
    });
    expect(job.status).toBe("completed");

    // The completed job should contain a preview_id in its result
    expect(job).toHaveProperty("result_json");
    const result =
      typeof job.result_json === "string"
        ? JSON.parse(job.result_json)
        : job.result_json;
    expect(result).toHaveProperty("preview_id");
  });

  // ── 3. GET /api/links/preview/{id}/candidates paginated ──

  test("GET /api/links/preview/{id}/candidates paginated — returns candidate list", async ({
    apiContext,
  }) => {
    // Create a preview first
    const createRes = await apiContext.post("/api/links/preview", {
      data: {
        family_id: FAMILIES.indebtedness,
        rule_id: RULES[0].rule_id,
        doc_ids: ["DOC-001", "DOC-002", "DOC-005"],
      },
    });
    const preview = await createRes.json();
    const previewId = preview.preview_id;

    // Fetch candidates with pagination
    const res = await apiContext.get(
      `/api/links/preview/${previewId}/candidates?page=1&page_size=10`,
    );
    expectOk(res);

    const body = await res.json();
    expectPaginated(body);
    expect(Array.isArray(body.items)).toBe(true);

    // Each candidate should have required fields
    for (const candidate of body.items) {
      expect(candidate).toHaveProperty("candidate_id");
      expect(candidate).toHaveProperty("doc_id");
      expect(candidate).toHaveProperty("section_number");
      expect(candidate).toHaveProperty("confidence");
      expect(candidate).toHaveProperty("user_verdict");
    }
  });

  // ── 4. PATCH /api/links/preview/{id}/candidates/{cid} ────

  test("PATCH /api/links/preview/{id}/candidates/{candidate_id} — sets user_verdict", async ({
    apiContext,
  }) => {
    // Create a preview
    const createRes = await apiContext.post("/api/links/preview", {
      data: {
        family_id: FAMILIES.indebtedness,
        rule_id: RULES[0].rule_id,
        doc_ids: ["DOC-001", "DOC-002", "DOC-005"],
      },
    });
    const preview = await createRes.json();
    const previewId = preview.preview_id;

    // Get the first candidate
    const listRes = await apiContext.get(
      `/api/links/preview/${previewId}/candidates`,
    );
    const listBody = await listRes.json();
    expect(listBody.items.length).toBeGreaterThan(0);

    const candidateId = listBody.items[0].candidate_id;

    // Set verdict to "accepted"
    const patchRes = await apiContext.patch(
      `/api/links/preview/${previewId}/candidates/${candidateId}`,
      {
        data: { user_verdict: "accepted" },
      },
    );
    expectOk(patchRes);

    const patchBody = await patchRes.json();
    expect(patchBody.candidate_id).toBe(candidateId);
    expect(patchBody.user_verdict).toBe("accepted");

    // Verify it persists on re-fetch
    const verifyRes = await apiContext.get(
      `/api/links/preview/${previewId}/candidates`,
    );
    const verifyBody = await verifyRes.json();
    const updated = verifyBody.items.find(
      (c: Record<string, unknown>) => c.candidate_id === candidateId,
    );
    expect(updated).toBeDefined();
    expect(updated.user_verdict).toBe("accepted");
  });

  // ── 5. POST /api/links/preview/{id}/apply success ────────

  test("POST /api/links/preview/{id}/apply success — creates links from accepted", async ({
    apiContext,
  }) => {
    // Create a preview
    const createRes = await apiContext.post("/api/links/preview", {
      data: {
        family_id: FAMILIES.indebtedness,
        rule_id: RULES[0].rule_id,
        doc_ids: ["DOC-001", "DOC-002", "DOC-005"],
      },
    });
    const preview = await createRes.json();
    const previewId = preview.preview_id;
    const contentHash = preview.content_hash;

    // Get candidates and accept them all
    const listRes = await apiContext.get(
      `/api/links/preview/${previewId}/candidates`,
    );
    const listBody = await listRes.json();

    for (const candidate of listBody.items) {
      await apiContext.patch(
        `/api/links/preview/${previewId}/candidates/${candidate.candidate_id}`,
        { data: { user_verdict: "accepted" } },
      );
    }

    // Apply the preview
    const applyRes = await apiContext.post(
      `/api/links/preview/${previewId}/apply`,
      {
        data: { content_hash: contentHash },
      },
    );
    expectOk(applyRes);

    const applyBody = await applyRes.json();
    expect(applyBody).toHaveProperty("created");
    expect(typeof applyBody.created).toBe("number");
    expect(applyBody).toHaveProperty("preview_id", previewId);
    expect(applyBody).toHaveProperty("status", "applied");

    // The number of created links should match accepted candidates
    const acceptedCount = listBody.items.length;
    expect(applyBody.created).toBe(acceptedCount);
  });

  // ── 6. POST /api/links/preview/{id}/apply rejects expired ─

  test("POST /api/links/preview/{id}/apply rejects expired — returns 409 for old previews", async ({
    apiContext,
  }) => {
    // Create a preview
    const createRes = await apiContext.post("/api/links/preview", {
      data: {
        family_id: FAMILIES.indebtedness,
        rule_id: RULES[0].rule_id,
        doc_ids: ["DOC-001"],
      },
    });
    const preview = await createRes.json();
    const previewId = preview.preview_id;
    const contentHash = preview.content_hash;

    // Force-expire the preview via the test endpoint
    const expireRes = await apiContext.post(
      `/api/links/_test/expire-preview/${previewId}`,
    );
    expectOk(expireRes);

    // Attempt to apply the expired preview
    const applyRes = await apiContext.post(
      `/api/links/preview/${previewId}/apply`,
      {
        data: { content_hash: contentHash },
      },
    );

    expect(applyRes.status()).toBe(409);
    const errorBody = await applyRes.json();
    expect(errorBody).toHaveProperty("detail");
    expect(typeof errorBody.detail).toBe("string");
  });

  // ── 7. POST /api/links/preview/{id}/apply rejects hash mismatch

  test("POST /api/links/preview/{id}/apply rejects hash mismatch — returns 409 for wrong hash", async ({
    apiContext,
  }) => {
    // Create a preview
    const createRes = await apiContext.post("/api/links/preview", {
      data: {
        family_id: FAMILIES.indebtedness,
        rule_id: RULES[0].rule_id,
        doc_ids: ["DOC-001"],
      },
    });
    const preview = await createRes.json();
    const previewId = preview.preview_id;

    // Apply with a deliberately wrong content_hash
    const applyRes = await apiContext.post(
      `/api/links/preview/${previewId}/apply`,
      {
        data: { content_hash: "wrong-hash-00000000" },
      },
    );

    expect(applyRes.status()).toBe(409);
    const errorBody = await applyRes.json();
    expect(errorBody).toHaveProperty("detail");
    expect(typeof errorBody.detail).toBe("string");
  });
});

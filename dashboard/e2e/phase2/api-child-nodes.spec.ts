/**
 * Phase 2 E2E: Child node linking operations.
 *
 * Tests child-linking job spawn, node CRUD, rule creation, preview,
 * candidate pagination, apply, scope enforcement, and unlinking.
 * All tests use the deterministic "minimal" seed dataset (10 links, 3 families).
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk, expectValidLink, expectPaginated } from "../helpers/link-assertions";
import { waitForJob } from "../helpers/wait-for-job";

test.describe("Child Nodes API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // ── 1. Start child-linking job ─────────────────────────────

  test("POST /api/links/{id}/start-child-linking spawns job", async ({
    apiContext,
  }) => {
    const linkId = "LINK-001"; // parent link: indebtedness, DOC-001, section 7.01

    const res = await apiContext.post(
      `/api/links/${linkId}/start-child-linking`,
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("job_id");
    expect(typeof body.job_id).toBe("string");
    expect(body.job_id.length).toBeGreaterThan(0);

    // Wait for the job to reach a terminal state
    const job = await waitForJob(apiContext, body.job_id, {
      timeoutMs: 30_000,
    });
    expect(job.status).toBe("completed");
  });

  // ── 2. Get child links (nodes) ─────────────────────────────

  test("GET /api/links/nodes returns child links", async ({
    apiContext,
  }) => {
    const parentId = "LINK-001";

    // Spawn the child-linking job and wait for completion
    const spawnRes = await apiContext.post(
      `/api/links/${parentId}/start-child-linking`,
    );
    expectOk(spawnRes);
    const { job_id } = await spawnRes.json();
    await waitForJob(apiContext, job_id, { timeoutMs: 30_000 });

    // Retrieve child nodes for the parent
    const res = await apiContext.get(
      `/api/links/nodes?parent_link_id=${parentId}`,
    );
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("items");
    expect(Array.isArray(body.items)).toBe(true);

    // Each node should reference the parent
    for (const node of body.items) {
      expect(node).toHaveProperty("node_id");
      expect(node).toHaveProperty("parent_link_id");
      expect(node.parent_link_id).toBe(parentId);
    }
  });

  // ── 3. Create node rule ────────────────────────────────────

  test("POST /api/links/node-rules creates rule", async ({
    apiContext,
  }) => {
    const nodeRule = {
      family_id: FAMILIES.indebtedness,
      pattern_type: "heading",
      pattern_value: "Permitted Indebtedness",
      scope: "subsection",
    };

    const res = await apiContext.post("/api/links/node-rules", {
      data: nodeRule,
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("rule_id");
    expect(body.family_id).toBe(FAMILIES.indebtedness);
    expect(body.pattern_type).toBe("heading");
    expect(body.pattern_value).toBe("Permitted Indebtedness");
    expect(body.scope).toBe("subsection");
  });

  // ── 4. Preview child nodes ─────────────────────────────────

  test("POST /api/links/nodes/preview creates child preview", async ({
    apiContext,
  }) => {
    const parentId = "LINK-001";
    const previewRequest = {
      parent_link_id: parentId,
      pattern_type: "heading",
      pattern_value: "Permitted",
    };

    const res = await apiContext.post("/api/links/nodes/preview", {
      data: previewRequest,
    });
    expectOk(res);

    const body = await res.json();
    expect(body).toHaveProperty("candidates");
    expect(Array.isArray(body.candidates)).toBe(true);

    // Each candidate should have the expected shape
    for (const candidate of body.candidates) {
      expect(candidate).toHaveProperty("section_number");
      expect(candidate).toHaveProperty("heading");
      expect(candidate).toHaveProperty("score");
      expect(typeof candidate.score).toBe("number");
    }
  });

  // ── 5. Candidates paginated ────────────────────────────────

  test("GET candidates paginated", async ({ apiContext }) => {
    const parentId = "LINK-001";

    // Spawn job first to ensure candidates exist
    const spawnRes = await apiContext.post(
      `/api/links/${parentId}/start-child-linking`,
    );
    expectOk(spawnRes);
    const { job_id } = await spawnRes.json();
    await waitForJob(apiContext, job_id, { timeoutMs: 30_000 });

    // Request page 1, limit 3
    const res = await apiContext.get(
      `/api/links/nodes?parent_link_id=${parentId}&offset=0&limit=3`,
    );
    expectOk(res);

    const body = await res.json();
    expectPaginated(body);
    expect(body).toHaveProperty("items");
    expect(Array.isArray(body.items)).toBe(true);
    expect(body.items.length).toBeLessThanOrEqual(3);

    // If there are more items than the page, request page 2
    if (body.total > 3) {
      const page2Res = await apiContext.get(
        `/api/links/nodes?parent_link_id=${parentId}&offset=3&limit=3`,
      );
      expectOk(page2Res);

      const page2Body = await page2Res.json();
      expect(page2Body).toHaveProperty("items");
      expect(Array.isArray(page2Body.items)).toBe(true);

      // Page 2 items should not overlap with page 1
      const page1Ids = new Set(
        body.items.map((n: Record<string, unknown>) => n.node_id),
      );
      for (const node of page2Body.items) {
        expect(page1Ids.has(node.node_id)).toBe(false);
      }
    }
  });

  // ── 6. Apply node links ────────────────────────────────────

  test("POST /api/links/nodes/apply creates node links", async ({
    apiContext,
  }) => {
    const parentId = "LINK-001";

    // First create a preview to get candidate IDs
    const previewRes = await apiContext.post("/api/links/nodes/preview", {
      data: {
        parent_link_id: parentId,
        pattern_type: "heading",
        pattern_value: "Permitted",
      },
    });
    expectOk(previewRes);
    const previewBody = await previewRes.json();

    // Apply the first candidate (if any exist)
    const candidateIds = previewBody.candidates.map(
      (c: Record<string, unknown>) => c.candidate_id,
    );

    const applyRes = await apiContext.post("/api/links/nodes/apply", {
      data: {
        parent_link_id: parentId,
        candidate_ids: candidateIds.length > 0 ? [candidateIds[0]] : [],
      },
    });
    expectOk(applyRes);

    const applyBody = await applyRes.json();
    expect(applyBody).toHaveProperty("created");
    expect(typeof applyBody.created).toBe("number");

    if (candidateIds.length > 0) {
      expect(applyBody.created).toBeGreaterThanOrEqual(1);
    }
  });

  // ── 7. Node link scoped to parent section only ─────────────

  test("Node link scoped to parent section only", async ({
    apiContext,
  }) => {
    const parentId = "LINK-001"; // DOC-001, section 7.01

    // Get the parent link's details to confirm section context
    const parentRes = await apiContext.get(`/api/links/${parentId}`);
    expectOk(parentRes);
    const parent = await parentRes.json();

    // Spawn child-linking and wait for completion
    const spawnRes = await apiContext.post(
      `/api/links/${parentId}/start-child-linking`,
    );
    expectOk(spawnRes);
    const { job_id } = await spawnRes.json();
    await waitForJob(apiContext, job_id, { timeoutMs: 30_000 });

    // Retrieve nodes and verify they are scoped to parent's doc + section
    const nodesRes = await apiContext.get(
      `/api/links/nodes?parent_link_id=${parentId}`,
    );
    expectOk(nodesRes);
    const nodesBody = await nodesRes.json();

    for (const node of nodesBody.items) {
      // All child nodes must reference the same doc as the parent
      expect(node.doc_id).toBe(parent.doc_id);
      // Child sections must be subsections of the parent section
      // e.g., parent is 7.01, children are 7.01(a), 7.01(b), etc.
      expect(node.section_number).toMatch(
        new RegExp(`^${parent.section_number.replace(".", "\\.")}`),
      );
    }
  });

  // ── 8. Unlink child node ───────────────────────────────────

  test("Unlink child node", async ({ apiContext }) => {
    const parentId = "LINK-001";

    // Spawn child-linking and wait
    const spawnRes = await apiContext.post(
      `/api/links/${parentId}/start-child-linking`,
    );
    expectOk(spawnRes);
    const { job_id } = await spawnRes.json();
    await waitForJob(apiContext, job_id, { timeoutMs: 30_000 });

    // Retrieve nodes to find one to unlink
    const nodesRes = await apiContext.get(
      `/api/links/nodes?parent_link_id=${parentId}`,
    );
    expectOk(nodesRes);
    const nodesBody = await nodesRes.json();

    // Skip if no child nodes were generated
    if (nodesBody.items.length === 0) {
      return;
    }

    const targetNodeId = nodesBody.items[0].node_id;

    // Unlink the child node
    const unlinkRes = await apiContext.patch(
      `/api/links/nodes/${targetNodeId}/unlink`,
      { data: { reason: "Not relevant subsection" } },
    );
    expectOk(unlinkRes);

    const unlinkBody = await unlinkRes.json();
    expect(unlinkBody.node_id).toBe(targetNodeId);
    expect(unlinkBody.status).toBe("unlinked");

    // Confirm via GET that the node is now unlinked
    const checkRes = await apiContext.get(
      `/api/links/nodes?parent_link_id=${parentId}`,
    );
    expectOk(checkRes);
    const checkBody = await checkRes.json();

    const unlinkedNode = checkBody.items.find(
      (n: Record<string, unknown>) => n.node_id === targetNodeId,
    );
    if (unlinkedNode) {
      expect(unlinkedNode.status).toBe("unlinked");
    }
  });
});

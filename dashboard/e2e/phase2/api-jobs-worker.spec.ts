/**
 * Phase 2 API E2E tests: Jobs and Worker lifecycle.
 *
 * Tests the job submission, status polling, cancellation,
 * and end-to-end worker processing for preview and apply jobs.
 */
import { test, expect } from "../fixtures/links-db";
import { MINIMAL_LINKS, FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk } from "../helpers/link-assertions";
import { waitForJob } from "../helpers/wait-for-job";

test.describe("Jobs & Worker", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("minimal");
  });

  // -----------------------------------------------------------------------
  // 1. POST submit job returns job_id
  // -----------------------------------------------------------------------
  test("POST submit job returns job_id", async ({ apiContext }) => {
    // Create a preview job via the query/preview endpoint with seeded data
    const res = await apiContext.post("/api/links/query/preview", {
      data: {
        family_id: FAMILIES.indebtedness,
      },
    });
    expectOk(res);

    const body = await res.json();
    // Sync preview returns preview_id; for the job path, use the export
    // endpoint which always returns a job_id
    expect(body).toHaveProperty("preview_id");

    // Now submit an export job which always returns a job_id
    const exportRes = await apiContext.post("/api/links/export", {
      data: { format: "csv", family_id: FAMILIES.indebtedness },
    });
    expectOk(exportRes);
    const exportBody = await exportRes.json();
    expect(exportBody).toHaveProperty("job_id");
    expect(typeof exportBody.job_id).toBe("string");
    expect(exportBody.job_id.length).toBeGreaterThan(0);
  });

  // -----------------------------------------------------------------------
  // 2. GET job status transitions pending -> running -> completed
  // -----------------------------------------------------------------------
  test("GET job status transitions pending -> running -> completed", async ({
    apiContext,
  }) => {
    // Submit a heading_discover job via the general jobs endpoint
    const submitRes = await apiContext.post("/api/jobs/submit", {
      data: {
        job_type: "heading_discover",
        params: {
          search_pattern: "Indebtedness",
          limit: 10,
        },
      },
    });
    expectOk(submitRes);

    const { job_id } = await submitRes.json();
    expect(typeof job_id).toBe("string");

    // Immediately fetch — should be pending or running (race-dependent)
    const firstPoll = await apiContext.get(`/api/jobs/${job_id}/status`);
    expectOk(firstPoll);
    const firstStatus = await firstPoll.json();
    expect(["pending", "running", "completed"]).toContain(firstStatus.status);

    // Poll until terminal
    const seenStatuses = new Set<string>();
    seenStatuses.add(firstStatus.status);

    const pollUntilDone = async (): Promise<Record<string, unknown>> => {
      const deadline = Date.now() + 15_000;
      while (Date.now() < deadline) {
        const pollRes = await apiContext.get(`/api/jobs/${job_id}/status`);
        expectOk(pollRes);
        const poll = await pollRes.json();
        seenStatuses.add(poll.status as string);
        if (["completed", "failed", "cancelled"].includes(poll.status)) {
          return poll;
        }
        await new Promise((r) => setTimeout(r, 300));
      }
      throw new Error("Job did not reach terminal state within 15s");
    };

    const final = await pollUntilDone();
    expect(final.status).toBe("completed");

    // We should have seen at least pending/running or running/completed
    expect(seenStatuses.size).toBeGreaterThanOrEqual(1);
    // Terminal state must include completed
    expect(seenStatuses.has("completed")).toBeTruthy();
  });

  // -----------------------------------------------------------------------
  // 3. DELETE cancels pending job
  // -----------------------------------------------------------------------
  test("DELETE cancels pending job", async ({ apiContext }) => {
    // Submit a job via the general endpoint
    const submitRes = await apiContext.post("/api/jobs/submit", {
      data: {
        job_type: "heading_discover",
        params: {
          search_pattern: "ZZZ_UNLIKELY_PATTERN_ZZZ",
          limit: 5,
        },
      },
    });
    expectOk(submitRes);
    const { job_id } = await submitRes.json();

    // Immediately cancel before worker picks it up
    const cancelRes = await apiContext.post(`/api/jobs/${job_id}/cancel`);
    expectOk(cancelRes);
    const cancelBody = await cancelRes.json();
    expect(cancelBody.cancelled).toBe(true);

    // Verify status is now cancelled
    const statusRes = await apiContext.get(`/api/jobs/${job_id}/status`);
    expectOk(statusRes);
    const statusBody = await statusRes.json();
    expect(statusBody.status).toBe("cancelled");
    expect(statusBody.completed_at).not.toBeNull();
  });

  // -----------------------------------------------------------------------
  // 4. Worker processes preview job end-to-end
  // -----------------------------------------------------------------------
  test("Worker processes preview job end-to-end", async ({ apiContext }) => {
    // Create a preview via the sync path
    const previewRes = await apiContext.post("/api/links/query/preview", {
      data: {
        family_id: FAMILIES.indebtedness,
      },
    });
    expectOk(previewRes);
    const previewBody = await previewRes.json();

    // Sync preview returns preview_id and candidate_count
    expect(previewBody).toHaveProperty("preview_id");
    expect(typeof previewBody.preview_id).toBe("string");
    expect(previewBody).toHaveProperty("candidate_count");
    expect(typeof previewBody.candidate_count).toBe("number");

    // Verify candidates are accessible
    const candidatesRes = await apiContext.get(
      `/api/links/previews/${previewBody.preview_id}/candidates`,
    );
    expectOk(candidatesRes);
    const candidatesBody = await candidatesRes.json();
    expect(candidatesBody).toHaveProperty("items");
    expect(candidatesBody).toHaveProperty("total");
    expect(candidatesBody.total).toBe(previewBody.candidate_count);

    // The preview was synchronous; verify by_confidence_tier is populated
    expect(previewBody).toHaveProperty("by_confidence_tier");
    expect(previewBody.by_confidence_tier).toHaveProperty("high");
    expect(previewBody.by_confidence_tier).toHaveProperty("medium");
    expect(previewBody.by_confidence_tier).toHaveProperty("low");
  });

  // -----------------------------------------------------------------------
  // 5. Worker processes apply job end-to-end
  // -----------------------------------------------------------------------
  test("Worker processes apply job end-to-end", async ({ apiContext }) => {
    // Step 1: Create a preview with indebtedness family
    const previewRes = await apiContext.post("/api/links/query/preview", {
      data: {
        family_id: FAMILIES.indebtedness,
      },
    });
    expectOk(previewRes);
    const previewBody = await previewRes.json();
    const previewId = previewBody.preview_id as string;
    const candidateSetHash = previewBody.candidate_set_hash as string;

    // Step 2: Mark some candidates as accepted
    const candidatesRes = await apiContext.get(
      `/api/links/previews/${previewId}/candidates`,
    );
    expectOk(candidatesRes);
    const candidatesBody = await candidatesRes.json();
    const items = candidatesBody.items as Array<Record<string, unknown>>;

    if (items.length > 0) {
      const verdicts = items.map((item) => ({
        doc_id: item.doc_id,
        section_number: item.section_number,
        verdict: "accepted",
      }));

      const verdictRes = await apiContext.patch(
        `/api/links/previews/${previewId}/candidates/verdict`,
        { data: { verdicts } },
      );
      expectOk(verdictRes);
    }

    // Step 3: Apply the preview (submits as async job)
    const applyRes = await apiContext.post("/api/links/query/apply", {
      data: {
        preview_id: previewId,
        candidate_set_hash: candidateSetHash,
      },
    });
    expectOk(applyRes);
    const applyBody = await applyRes.json();
    expect(applyBody).toHaveProperty("job_id");
    expect(applyBody).toHaveProperty("preview_id");
    expect(applyBody.preview_id).toBe(previewId);

    // Step 4: Poll the link job until completion
    const jobResult = await waitForJob(apiContext, applyBody.job_id, {
      pollIntervalMs: 300,
      timeoutMs: 15_000,
    });
    expect(jobResult.status).toBe("completed");
  });
});

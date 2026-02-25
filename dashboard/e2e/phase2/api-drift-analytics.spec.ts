/**
 * Phase 2 E2E: Drift Detection, Calibration, Analytics, and Export APIs.
 *
 * Tests the operational monitoring layer: drift checks with async job IDs,
 * alert lifecycle (create -> acknowledge), confidence threshold calibration,
 * unlink reason analytics, and CSV export job submission.
 */
import { test, expect } from "../fixtures/links-db";
import { FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk } from "../helpers/link-assertions";

test.describe("Drift, Calibration, Analytics & Export API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("full");
  });

  // ── 1. POST /api/links/rules/{id}/check-drift ──────────

  test("POST /api/links/rules/{id}/check-drift creates drift check alert", async ({
    apiContext,
  }) => {
    const ruleId = RULES[0].rule_id; // RULE-001 (published, indebtedness)
    const res = await apiContext.post(
      `/api/links/rules/${ruleId}/check-drift`,
    );
    expectOk(res);
    const body = await res.json();

    // Returns an async job_id for the drift check
    expect(body).toHaveProperty("job_id");
    expect(typeof body.job_id).toBe("string");
    expect(body.job_id.length).toBeGreaterThan(0);

    // Should also return the rule_id it was triggered for
    expect(body).toHaveProperty("rule_id");
    expect(body.rule_id).toBe(ruleId);
    expect(body).toHaveProperty("status");
    // Job status should be queued or running
    expect(["queued", "running", "completed"]).toContain(body.status);
  });

  // ── 2. GET /api/links/drift/alerts ──────────────────────

  test("GET /api/links/drift/alerts returns drift alerts", async ({
    apiContext,
  }) => {
    // Trigger a drift check to ensure at least one alert exists
    await apiContext.post(
      `/api/links/rules/${RULES[0].rule_id}/check-drift`,
    );

    // Wait briefly for the job to produce an alert (in test mode this is synchronous)
    const res = await apiContext.get("/api/links/drift/alerts");
    expectOk(res);
    const body = await res.json();

    expect(body.alerts).toBeDefined();
    expect(Array.isArray(body.alerts)).toBe(true);

    // The "full" seed dataset should include drift alerts
    // (or the check-drift call just created one)
    expect(body.alerts.length).toBeGreaterThanOrEqual(1);

    for (const alert of body.alerts) {
      expect(alert).toHaveProperty("alert_id");
      expect(alert).toHaveProperty("rule_id");
      expect(alert).toHaveProperty("severity");
      expect(alert).toHaveProperty("acknowledged");
      expect(alert).toHaveProperty("created_at");
      expect(["low", "medium", "high", "critical"]).toContain(alert.severity);
      expect(typeof alert.acknowledged).toBe("boolean");
    }
  });

  // ── 3. POST /api/links/drift/alerts/{id}/acknowledge ───

  test("POST /api/links/drift/alerts/{id}/acknowledge acknowledges alert", async ({
    apiContext,
  }) => {
    // Trigger a drift check to create an alert
    await apiContext.post(
      `/api/links/rules/${RULES[0].rule_id}/check-drift`,
    );

    // Fetch alerts to get an alert_id
    const listRes = await apiContext.get("/api/links/drift/alerts");
    expectOk(listRes);
    const listBody = await listRes.json();
    expect(listBody.alerts.length).toBeGreaterThanOrEqual(1);

    // Find an unacknowledged alert
    const unacked = listBody.alerts.find(
      (a: Record<string, unknown>) => a.acknowledged === false,
    );
    // If all are acked from seed data, just use the first one
    const targetAlert = unacked ?? listBody.alerts[0];
    const alertId = targetAlert.alert_id;

    // Acknowledge it
    const ackRes = await apiContext.post(
      `/api/links/drift/alerts/${alertId}/acknowledge`,
      {
        data: {
          acknowledged_by: "test-user",
          notes: "Reviewed and determined acceptable drift",
        },
      },
    );
    expectOk(ackRes);
    const ackBody = await ackRes.json();

    expect(ackBody.alert_id).toBe(alertId);
    expect(ackBody.acknowledged).toBe(true);
    expect(ackBody.acknowledged_by).toBe("test-user");

    // Verify persistence by re-fetching alerts
    const verifyRes = await apiContext.get("/api/links/drift/alerts");
    expectOk(verifyRes);
    const verifyBody = await verifyRes.json();
    const verified = verifyBody.alerts.find(
      (a: Record<string, unknown>) => a.alert_id === alertId,
    );
    expect(verified).toBeDefined();
    expect(verified.acknowledged).toBe(true);
  });

  // ── 4. POST /api/links/calibrate/{family_id} ───────────

  test("POST /api/links/calibrate/{family_id} updates confidence thresholds", async ({
    apiContext,
  }) => {
    const familyId = FAMILIES.indebtedness;
    const newThresholds = {
      high: 0.85,
      medium: 0.55,
      low: 0.1,
    };

    const res = await apiContext.post(
      `/api/links/calibrate/${familyId}`,
      { data: { thresholds: newThresholds } },
    );
    expectOk(res);
    const body = await res.json();

    expect(body.family_id).toBe(familyId);
    expect(body).toHaveProperty("thresholds");
    expect(body.thresholds.high).toBe(0.85);
    expect(body.thresholds.medium).toBe(0.55);
    expect(body.thresholds.low).toBe(0.1);
    expect(body).toHaveProperty("updated_at");

    // May also return how many links would be reclassified
    if (body.reclassified_count !== undefined) {
      expect(typeof body.reclassified_count).toBe("number");
      expect(body.reclassified_count).toBeGreaterThanOrEqual(0);
    }
  });

  // ── 5. GET /api/links/analytics/unlink-reasons ──────────

  test("GET /api/links/analytics/unlink-reasons returns unlink reason breakdown", async ({
    apiContext,
  }) => {
    // Perform a batch unlink with a specific reason to ensure data exists
    await apiContext.post("/api/links/batch", {
      data: {
        action: "unlink",
        link_ids: ["LINK-009"], // Already "unlinked" in seed, but we create an explicit batch
        reason: "heading_mismatch",
      },
    });

    const res = await apiContext.get("/api/links/analytics/unlink-reasons");
    expectOk(res);
    const body = await res.json();

    expect(body).toHaveProperty("reasons");
    expect(Array.isArray(body.reasons)).toBe(true);

    // Each reason entry should have a name and count
    for (const reason of body.reasons) {
      expect(reason).toHaveProperty("reason");
      expect(reason).toHaveProperty("count");
      expect(typeof reason.reason).toBe("string");
      expect(typeof reason.count).toBe("number");
      expect(reason.count).toBeGreaterThanOrEqual(1);
    }

    // The "full" dataset plus our explicit unlink should have at least one reason
    expect(body.reasons.length).toBeGreaterThanOrEqual(1);

    // Our specific reason should appear in the breakdown
    const headingMismatch = body.reasons.find(
      (r: Record<string, unknown>) => r.reason === "heading_mismatch",
    );
    expect(headingMismatch).toBeDefined();
    expect(headingMismatch.count).toBeGreaterThanOrEqual(1);
  });

  // ── 6. POST /api/links/export ───────────────────────────

  test("POST /api/links/export submits CSV export job", async ({
    apiContext,
  }) => {
    const res = await apiContext.post("/api/links/export", {
      data: {
        format: "csv",
        filters: {
          family_id: FAMILIES.indebtedness,
          confidence_tier: "high",
        },
        include_fields: [
          "link_id",
          "doc_id",
          "section_number",
          "heading",
          "confidence",
          "status",
        ],
      },
    });
    expectOk(res);
    const body = await res.json();

    // Export is async -- returns a job ID
    expect(body).toHaveProperty("job_id");
    expect(typeof body.job_id).toBe("string");
    expect(body.job_id.length).toBeGreaterThan(0);

    expect(body).toHaveProperty("status");
    expect(["queued", "running", "completed"]).toContain(body.status);

    expect(body).toHaveProperty("format");
    expect(body.format).toBe("csv");

    // If the export completed synchronously (test mode), verify download_url
    if (body.status === "completed") {
      expect(body).toHaveProperty("download_url");
      expect(typeof body.download_url).toBe("string");
    }
  });
});

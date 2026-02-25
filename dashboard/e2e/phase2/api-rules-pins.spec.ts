/**
 * Phase 2 E2E: Rules, Pins, Evaluation, and Promotion APIs.
 *
 * Tests the rule lifecycle from listing through cloning, pinning
 * (TP/TN), pin evaluation, and promotion.
 */
import { test, expect } from "../fixtures/links-db";
import { FAMILIES, RULES } from "../fixtures/seed-data";
import { expectOk, expectValidRule } from "../helpers/link-assertions";

test.describe("Rules & Pins API", () => {
  test.beforeEach(async ({ resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("rules");
  });

  // ── 1. GET /api/links/rules ─────────────────────────────

  test("GET /api/links/rules returns rules list", async ({ apiContext }) => {
    const res = await apiContext.get("/api/links/rules");
    expectOk(res);
    const body = await res.json();

    expect(body.rules).toBeDefined();
    expect(Array.isArray(body.rules)).toBe(true);
    expect(body.rules.length).toBeGreaterThanOrEqual(RULES.length);

    // Every returned rule should have the required shape
    for (const rule of body.rules) {
      expectValidRule(rule);
    }

    // Our seeded rules should be present
    const ruleIds = body.rules.map((r: Record<string, unknown>) => r.rule_id);
    expect(ruleIds).toContain(RULES[0].rule_id);
    expect(ruleIds).toContain(RULES[1].rule_id);
    expect(ruleIds).toContain(RULES[2].rule_id);
  });

  // ── 2. POST /api/links/rules ────────────────────────────

  test("POST /api/links/rules creates a new rule", async ({ apiContext }) => {
    const newRule = {
      family_id: FAMILIES.investments,
      heading_filter_ast: {
        type: "group",
        operator: "or",
        children: [
          { type: "match", value: "Investments" },
          { type: "match", value: "Permitted Investments" },
        ],
      },
      status: "draft",
    };

    const res = await apiContext.post("/api/links/rules", { data: newRule });
    expectOk(res);
    const body = await res.json();

    expect(body.rule_id).toBeDefined();
    expect(body.family_id).toBe(FAMILIES.investments);
    expect(body.status).toBe("draft");
    expect(body.version).toBe(1);
    expectValidRule(body);

    // Confirm it appears in the listing
    const listRes = await apiContext.get("/api/links/rules");
    expectOk(listRes);
    const listBody = await listRes.json();
    const ids = listBody.rules.map((r: Record<string, unknown>) => r.rule_id);
    expect(ids).toContain(body.rule_id);
  });

  // ── 3. POST /api/links/rules/{id}/clone ─────────────────

  test("POST /api/links/rules/{id}/clone clones a rule with new version", async ({
    apiContext,
  }) => {
    const originalId = RULES[0].rule_id; // RULE-001, published, version 1
    const res = await apiContext.post(
      `/api/links/rules/${originalId}/clone`,
    );
    expectOk(res);
    const body = await res.json();

    // Cloned rule gets a new ID and incremented version
    expect(body.rule_id).toBeDefined();
    expect(body.rule_id).not.toBe(originalId);
    expect(body.family_id).toBe(RULES[0].family_id);
    expect(body.version).toBeGreaterThan(RULES[0].version);
    // Clone starts as draft regardless of source status
    expect(body.status).toBe("draft");
    expectValidRule(body);
  });

  // ── 4. POST /api/links/rules/{id}/pins (TP type) ───────

  test("POST /api/links/rules/{id}/pins creates a TP pin", async ({
    apiContext,
  }) => {
    const ruleId = RULES[0].rule_id;
    const pin = {
      pin_type: "TP",
      doc_id: "DOC-001",
      section_number: "7.01",
      heading: "Indebtedness",
      expected: true,
      notes: "Known true positive for indebtedness heading",
    };

    const res = await apiContext.post(
      `/api/links/rules/${ruleId}/pins`,
      { data: pin },
    );
    expectOk(res);
    const body = await res.json();

    expect(body.pin_id).toBeDefined();
    expect(body.pin_type).toBe("TP");
    expect(body.doc_id).toBe("DOC-001");
    expect(body.section_number).toBe("7.01");
    expect(body.expected).toBe(true);
  });

  // ── 5. POST /api/links/rules/{id}/pins (TN type) ───────

  test("POST /api/links/rules/{id}/pins creates a TN pin", async ({
    apiContext,
  }) => {
    const ruleId = RULES[0].rule_id;
    const pin = {
      pin_type: "TN",
      doc_id: "DOC-005",
      section_number: "8.01",
      heading: "Events of Default",
      expected: false,
      notes: "Events of Default should NOT match indebtedness",
    };

    const res = await apiContext.post(
      `/api/links/rules/${ruleId}/pins`,
      { data: pin },
    );
    expectOk(res);
    const body = await res.json();

    expect(body.pin_id).toBeDefined();
    expect(body.pin_type).toBe("TN");
    expect(body.doc_id).toBe("DOC-005");
    expect(body.expected).toBe(false);
  });

  // ── 6. GET /api/links/rules/{id}/pins ───────────────────

  test("GET /api/links/rules/{id}/pins returns pins for a rule", async ({
    apiContext,
  }) => {
    const ruleId = RULES[0].rule_id;

    // Create two pins first
    await apiContext.post(`/api/links/rules/${ruleId}/pins`, {
      data: {
        pin_type: "TP",
        doc_id: "DOC-001",
        section_number: "7.01",
        heading: "Indebtedness",
        expected: true,
      },
    });
    await apiContext.post(`/api/links/rules/${ruleId}/pins`, {
      data: {
        pin_type: "TN",
        doc_id: "DOC-005",
        section_number: "8.01",
        heading: "Events of Default",
        expected: false,
      },
    });

    const res = await apiContext.get(`/api/links/rules/${ruleId}/pins`);
    expectOk(res);
    const body = await res.json();

    expect(body.pins).toBeDefined();
    expect(Array.isArray(body.pins)).toBe(true);
    expect(body.pins.length).toBeGreaterThanOrEqual(2);

    const pinTypes = body.pins.map((p: Record<string, unknown>) => p.pin_type);
    expect(pinTypes).toContain("TP");
    expect(pinTypes).toContain("TN");

    // Each pin should have required fields
    for (const pin of body.pins) {
      expect(pin).toHaveProperty("pin_id");
      expect(pin).toHaveProperty("pin_type");
      expect(pin).toHaveProperty("doc_id");
      expect(pin).toHaveProperty("expected");
    }
  });

  // ── 7. POST /api/links/rules/{id}/evaluate-pins ────────

  test("POST /api/links/rules/{id}/evaluate-pins all pins pass", async ({
    apiContext,
  }) => {
    const ruleId = RULES[0].rule_id;

    // Pin a known TP: DOC-001 section 7.01 "Indebtedness" should match
    await apiContext.post(`/api/links/rules/${ruleId}/pins`, {
      data: {
        pin_type: "TP",
        doc_id: "DOC-001",
        section_number: "7.01",
        heading: "Indebtedness",
        expected: true,
      },
    });

    // Pin a known TN: "Events of Default" should not match indebtedness rule
    await apiContext.post(`/api/links/rules/${ruleId}/pins`, {
      data: {
        pin_type: "TN",
        doc_id: "DOC-005",
        section_number: "8.01",
        heading: "Events of Default",
        expected: false,
      },
    });

    const res = await apiContext.post(
      `/api/links/rules/${ruleId}/evaluate-pins`,
    );
    expectOk(res);
    const body = await res.json();

    expect(body).toHaveProperty("passed");
    expect(body).toHaveProperty("results");
    expect(Array.isArray(body.results)).toBe(true);
    expect(body.results.length).toBeGreaterThanOrEqual(2);

    // All pins should pass (expected matches actual)
    expect(body.passed).toBe(true);
    for (const result of body.results) {
      expect(result).toHaveProperty("pin_id");
      expect(result).toHaveProperty("actual");
      expect(result).toHaveProperty("pass");
      expect(result.pass).toBe(true);
    }
  });

  // ── 8. POST /api/links/rules/{id}/promote ──────────────

  test("POST /api/links/rules/{id}/promote promotion with all gates passing", async ({
    apiContext,
  }) => {
    // Create a fresh draft rule
    const createRes = await apiContext.post("/api/links/rules", {
      data: {
        family_id: FAMILIES.liens,
        heading_filter_ast: {
          type: "group",
          operator: "or",
          children: [
            { type: "match", value: "Liens" },
            { type: "match", value: "Limitation on Liens" },
          ],
        },
        status: "draft",
      },
    });
    expectOk(createRes);
    const created = await createRes.json();
    const ruleId = created.rule_id;

    // Add a TP pin so evaluation gate has something to validate
    await apiContext.post(`/api/links/rules/${ruleId}/pins`, {
      data: {
        pin_type: "TP",
        doc_id: "DOC-001",
        section_number: "7.02",
        heading: "Liens",
        expected: true,
      },
    });

    // Promote: transitions draft -> published after passing all gates
    const res = await apiContext.post(
      `/api/links/rules/${ruleId}/promote`,
    );
    expectOk(res);
    const body = await res.json();

    expect(body.rule_id).toBe(ruleId);
    expect(body.status).toBe("published");
    expect(body).toHaveProperty("gates");
    expect(body.gates).toHaveProperty("pins_passed");
    expect(body.gates.pins_passed).toBe(true);

    // Confirm status persisted by re-fetching
    const rulesRes = await apiContext.get("/api/links/rules");
    expectOk(rulesRes);
    const rulesBody = await rulesRes.json();
    const promoted = rulesBody.rules.find(
      (r: Record<string, unknown>) => r.rule_id === ruleId,
    );
    expect(promoted).toBeDefined();
    expect(promoted.status).toBe("published");
  });
});

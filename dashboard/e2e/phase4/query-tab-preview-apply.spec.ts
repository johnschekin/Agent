/**
 * Phase 4 E2E: Query tab preview/apply flow.
 *
 * Validates network-backed preview lifecycle, verdicting, canary/apply, and rule save.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

async function openQueryWithFamily(page: import("@playwright/test").Page) {
  await page.goto(`${FRONTEND_BASE}/links`);
  await page.waitForLoadState("networkidle");
  await page.locator("button").filter({ hasText: /indebtedness/i }).first().click();
  await page.getByTestId("tab-query").click();
  await expect(page.getByTestId("query-tab")).toBeVisible();
}

async function buildSimpleAst(page: import("@playwright/test").Page, term = "Indebtedness") {
  await page.getByTestId("ast-builder-init").click();
  await page.getByTestId("add-match-root").click();
  await page.getByTestId("match-input-children.0").fill(term);
}

async function createPreview(page: import("@playwright/test").Page) {
  const previewResponse = page.waitForResponse((res) =>
    res.url().includes("/api/links/query/preview") &&
    res.request().method() === "POST",
  );
  await page.getByTestId("query-preview-btn").click();
  const response = await previewResponse;
  expect(response.ok()).toBeTruthy();
  const body = (await response.json()) as Record<string, unknown>;
  expect(String(body.preview_id ?? "")).not.toBe("");
  await expect(page.getByTestId("preview-tier-all")).toBeVisible();
  await expect(page.locator('[data-testid^="preview-candidate-"]').first()).toBeVisible();
  return body;
}

test.describe("Query Tab — Preview & Apply", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("rules");
    await openQueryWithFamily(page);
  });

  test("preview button remains disabled until AST exists", async ({ page }) => {
    await expect(page.getByTestId("query-preview-btn")).toBeDisabled();
    await buildSimpleAst(page);
    await expect(page.getByTestId("query-preview-btn")).toBeEnabled();
  });

  test("creates preview and renders candidate rows", async ({ page }) => {
    await buildSimpleAst(page);
    await createPreview(page);
    const candidates = page.locator('[data-testid^="preview-candidate-"]');
    expect(await candidates.count()).toBeGreaterThan(0);
  });

  test("tier filter triggers candidates refetch with confidence_tier", async ({ page }) => {
    await buildSimpleAst(page);
    await createPreview(page);

    const tierResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/previews/") &&
      res.url().includes("confidence_tier=high") &&
      res.request().method() === "GET",
    );
    await page.getByTestId("preview-tier-high").click();
    const response = await tierResponse;
    expect(response.ok()).toBeTruthy();
  });

  test("accept verdict calls verdict endpoint and updates row state", async ({ page }) => {
    await buildSimpleAst(page);
    await createPreview(page);
    const firstCandidate = page.locator('[data-testid^="preview-candidate-"]').first();
    const docIdAttr = await firstCandidate.getAttribute("data-testid");
    expect(docIdAttr).toBeTruthy();
    const docId = String(docIdAttr).replace("preview-candidate-", "");

    const verdictResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/previews/") &&
      res.url().includes("/candidates/verdict") &&
      res.request().method() === "PATCH",
    );
    await page.getByTestId(`verdict-accept-${docId}`).click();
    const response = await verdictResponse;
    expect(response.ok()).toBeTruthy();
    await expect(page.getByTestId(`verdict-accept-${docId}`)).toHaveClass(/bg-glow-green/);
  });

  test("apply preview posts candidate hash and returns queued job", async ({ page }) => {
    await buildSimpleAst(page);
    await createPreview(page);

    const applyResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/query/apply") &&
      res.request().method() === "POST",
    );
    await page.getByTestId("query-apply-btn").click();
    const response = await applyResponse;
    expect(response.ok()).toBeTruthy();
    const body = (await response.json()) as Record<string, unknown>;
    expect(String(body.job_id ?? "")).not.toBe("");
  });

  test("canary apply returns delta payload", async ({ page }) => {
    await buildSimpleAst(page);
    await createPreview(page);

    const canaryResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/query/canary") &&
      res.request().method() === "POST",
    );
    await page.getByTestId("query-canary-btn").click();
    const response = await canaryResponse;
    expect(response.ok()).toBeTruthy();
    const body = (await response.json()) as Record<string, unknown>;
    const delta = (body.delta ?? {}) as Record<string, unknown>;
    expect(Number(delta.canary_n ?? 0)).toBe(10);
  });

  test("save as rule persists draft rule for selected family", async ({ page, apiContext }) => {
    await buildSimpleAst(page, "Debt Limitations");
    await createPreview(page);

    const createRuleResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/rules") &&
      res.request().method() === "POST",
    );
    await page.getByTestId("query-save-rule-btn").click();
    const response = await createRuleResponse;
    expect(response.ok()).toBeTruthy();

    const rulesRes = await apiContext.get("/api/links/rules?family_id=FAM-indebtedness");
    expect(rulesRes.ok()).toBeTruthy();
    const rulesBody = await rulesRes.json();
    const rules = Array.isArray(rulesBody.rules) ? rulesBody.rules : [];
    const hasDebtRule = rules.some((row: Record<string, unknown>) =>
      JSON.stringify(row.heading_filter_ast ?? {}).includes("Debt Limitations"),
    );
    expect(hasDebtRule).toBeTruthy();
  });

  test("AST edit updates DSL text (builder -> text sync)", async ({ page }) => {
    await buildSimpleAst(page, "Financial Covenants");
    await expect(page.getByTestId("text-query-bar-input")).toHaveValue(/Financial Covenants/);
  });

  test("409 apply errors are surfaced in query tab", async ({ page }) => {
    await buildSimpleAst(page);
    await createPreview(page);

    await page.route("**/api/links/query/apply", async (route) => {
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Candidate set hash mismatch" }),
      });
    });
    await page.getByTestId("query-apply-btn").click();
    await expect(page.getByTestId("apply-error")).toContainText(/hash mismatch|expired/i);
    await page.unroute("**/api/links/query/apply");
  });
});

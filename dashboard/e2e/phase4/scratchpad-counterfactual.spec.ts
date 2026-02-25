/**
 * Phase 4 E2E: Scratchpad and counterfactual diagnostics.
 *
 * Validates live evaluate-text and why-not mute/unmute counterfactual flow.
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

async function openCoverageWithFamily(page: import("@playwright/test").Page) {
  await page.goto(`${FRONTEND_BASE}/links`);
  await page.waitForLoadState("networkidle");
  await page.locator("button").filter({ hasText: /indebtedness/i }).first().click();
  await page.getByTestId("tab-coverage").click();
  await expect(page.getByTestId("coverage-tab")).toBeVisible();
}

async function initAst(page: import("@playwright/test").Page, term: string) {
  await page.getByTestId("ast-builder-init").click();
  await page.getByTestId("add-match-root").click();
  await page.getByTestId("match-input-children.0").fill(term);
}

test.describe("Scratchpad", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("rules");
    await openQueryWithFamily(page);
  });

  test("scratchpad toggles open/closed", async ({ page }) => {
    const toggle = page.getByTestId("toggle-scratchpad");
    await toggle.click();
    await expect(page.getByTestId("scratchpad-pane")).toBeVisible();
    await toggle.click();
    await expect(page.getByTestId("scratchpad-pane")).toBeHidden();
  });

  test("typing text triggers evaluate-text endpoint and renders traffic tree", async ({ page }) => {
    await initAst(page, "covenants");
    await page.getByTestId("toggle-scratchpad").click();

    const evaluateResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/rules/evaluate-text") &&
      res.request().method() === "POST",
    );
    await page.getByTestId("scratchpad-textarea").fill("financial covenants are limited here");
    const response = await evaluateResponse;
    expect(response.ok()).toBeTruthy();

    const body = (await response.json()) as Record<string, unknown>;
    expect(typeof body.matched).toBe("boolean");
    await expect(page.getByTestId("scratchpad-banner")).toBeVisible();
    await expect(page.getByTestId("traffic-light-ast")).toBeVisible();
  });

  test("scratchpad result updates after changing text", async ({ page }) => {
    await initAst(page, "indebtedness");
    await page.getByTestId("toggle-scratchpad").click();
    const textarea = page.getByTestId("scratchpad-textarea");

    await textarea.fill("this section discusses liens only");
    await page.waitForResponse((res) =>
      res.url().includes("/api/links/rules/evaluate-text") &&
      res.request().method() === "POST",
    );
    await expect(page.getByTestId("scratchpad-banner")).toContainText(/MATCH|NO MATCH/);

    await textarea.fill("the indebtedness covenant is tested");
    await page.waitForResponse((res) =>
      res.url().includes("/api/links/rules/evaluate-text") &&
      res.request().method() === "POST",
    );
    await expect(page.getByTestId("scratchpad-banner")).toContainText(/MATCH|NO MATCH/);
  });
});

test.describe("Counterfactual Why-Not", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("coverage");
    await openCoverageWithFamily(page);
  });

  test("gap click opens why-not panel and fetches diagnostic tree", async ({ page }) => {
    const gapRow = page.locator('[data-testid^="gap-row-"]').first();
    await expect(gapRow).toBeVisible();
    const whyNotResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/coverage/why-not") &&
      res.request().method() === "POST",
    );
    await gapRow.click();
    const response = await whyNotResponse;
    expect(response.ok()).toBeTruthy();
    await expect(page.getByTestId("why-not-panel")).toBeVisible();
    await expect(page.getByTestId("traffic-light-ast")).toBeVisible();
  });

  test("muting a red node calls counterfactual endpoint and marks node muted", async ({ page }) => {
    const gapRow = page.locator('[data-testid^="gap-row-"]').first();
    await gapRow.click();
    await expect(page.getByTestId("why-not-panel")).toBeVisible();

    const redChip = page
      .getByTestId("why-not-panel")
      .locator('[data-testid^="traffic-chip-"].bg-glow-red')
      .first();
    await expect(redChip).toBeVisible();

    const counterfactualResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/coverage/counterfactual") &&
      res.request().method() === "POST",
    );
    await redChip.click();
    const response = await counterfactualResponse;
    expect(response.ok()).toBeTruthy();

    const mutedChip = page
      .getByTestId("why-not-panel")
      .locator('[data-testid^="traffic-chip-"].line-through')
      .first();
    await expect(mutedChip).toBeVisible();
  });

  test("clicking muted node un-mutes it", async ({ page }) => {
    const gapRow = page.locator('[data-testid^="gap-row-"]').first();
    await gapRow.click();
    await expect(page.getByTestId("why-not-panel")).toBeVisible();

    const redChip = page
      .getByTestId("why-not-panel")
      .locator('[data-testid^="traffic-chip-"].bg-glow-red')
      .first();
    await expect(redChip).toBeVisible();
    const counterfactualResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/coverage/counterfactual") &&
      res.request().method() === "POST",
    );
    await redChip.click();
    const response = await counterfactualResponse;
    expect(response.ok()).toBeTruthy();

    const mutedChip = page
      .getByTestId("why-not-panel")
      .locator('[data-testid^="traffic-chip-"].line-through')
      .first();
    await expect(mutedChip).toBeVisible();
    await mutedChip.click();
    await expect(
      page.getByTestId("why-not-panel").locator('[data-testid^="traffic-chip-"].line-through'),
    ).toHaveCount(0);
  });
});

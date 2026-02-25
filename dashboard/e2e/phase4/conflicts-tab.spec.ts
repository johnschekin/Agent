/**
 * Phase 4 E2E: Conflicts tab tests.
 *
 * Validates deterministic conflict rendering and resolution side-effects.
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

async function openFirstConflict(page: import("@playwright/test").Page) {
  const row = page.locator('[data-testid^="conflict-row-"]').first();
  await expect(row).toBeVisible();
  await row.click();
  await expect(page.getByTestId("conflict-resolver")).toBeVisible();
}

test.describe("Conflicts Tab", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("conflicts");
    await page.goto(`${FRONTEND_BASE}/links?tab=conflicts`);
    await page.waitForLoadState("networkidle");
  });

  test("renders seeded conflict row with deterministic section + families", async ({ page }) => {
    await expect(page.getByTestId("conflicts-tab")).toBeVisible();
    const row = page.getByTestId("conflict-row-DOC-020");
    await expect(row).toBeVisible();
    await expect(row).toContainText("7.03");
    await expect(row).toContainText("Shared Covenant");
    await expect(row).toContainText("FAM-indebtedness");
    await expect(row).toContainText("FAM-liens");
  });

  test("resolver displays per-family evidence metadata", async ({ page }) => {
    await openFirstConflict(page);
    const famA = page.getByTestId("conflict-family-FAM-indebtedness");
    const famB = page.getByTestId("conflict-family-FAM-liens");
    await expect(famA).toContainText("unique evidence");
    await expect(famB).toContainText("unique evidence");
  });

  test("winner resolution unlinks losing family link and clears conflict", async ({ page, apiContext }) => {
    await openFirstConflict(page);
    await page.getByTestId("winner-family-select").selectOption("FAM-indebtedness");

    const unlinkResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/batch/unlink") &&
      res.request().method() === "POST",
    );
    await page.getByTestId("conflict-apply").click();
    const unlinkRes = await unlinkResponse;
    expect(unlinkRes.ok()).toBeTruthy();

    const loserLink = await apiContext.get("/api/links/LINK-C002");
    expect(loserLink.ok()).toBeTruthy();
    const loserBody = await loserLink.json();
    expect(String(loserBody.status)).toBe("unlinked");

    const conflictsRes = await apiContext.get("/api/links/conflicts");
    expect(conflictsRes.ok()).toBeTruthy();
    const conflictsBody = await conflictsRes.json();
    expect(Number(conflictsBody.total ?? 0)).toBe(0);
  });

  test("compound covenant rejects when independent evidence is missing", async ({ page }) => {
    await openFirstConflict(page);
    await page.getByTestId("resolution-compound").click();
    await page.getByTestId("conflict-apply").click();
    const validationError = page.getByTestId("compound-validation-error");
    await expect(validationError).toBeVisible();
    await expect(validationError).toContainText("Independent evidence required");
  });

  test("split option opens splitter UI", async ({ page }) => {
    await openFirstConflict(page);
    await page.getByTestId("resolution-split").click();
    await expect(page.getByTestId("sub-clause-splitter")).toBeVisible();
    await expect(page.getByTestId("splitter-text")).toBeVisible();
    await expect(page.getByTestId("splitter-apply")).toBeVisible();
  });

  test("meta-rule creation persists conflict policy override", async ({ page, apiContext }) => {
    await openFirstConflict(page);
    await page.getByTestId("create-meta-rule-toggle").click();
    await page.getByTestId("meta-rule-policy-select").selectOption("exclusive");
    await page.locator("textarea[placeholder='Reason (optional)']").fill("e2e override");

    const saveResponse = page.waitForResponse((res) =>
      res.url().includes("/api/links/conflict-policies") &&
      res.request().method() === "POST",
    );
    await page.getByTestId("save-meta-rule").click();
    const saveRes = await saveResponse;
    expect(saveRes.ok()).toBeTruthy();

    const policiesRes = await apiContext.get("/api/links/conflict-policies");
    expect(policiesRes.ok()).toBeTruthy();
    const policiesBody = await policiesRes.json();
    const policies = Array.isArray(policiesBody.policies) ? policiesBody.policies : [];
    const override = policies.find(
      (row: Record<string, unknown>) =>
        String(row.family_a) === "FAM-indebtedness" &&
        String(row.family_b) === "FAM-liens" &&
        String(row.policy) === "exclusive",
    );
    expect(override).toBeTruthy();
  });
});

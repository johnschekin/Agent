/**
 * Phase 5 E2E: Export/Import dialog tests.
 *
 * Tests dialog open/close, export format selection,
 * import tab, file upload preview, and trigger actions.
 *
 * Verified testids from ExportImportDialog.tsx:
 *   export-import-dialog, export-import-close, export-tab, import-tab,
 *   export-format-{csv|jsonl|json|replay}, export-btn, import-dropzone,
 *   import-file-input, import-btn, import-preview-table, import-preview-row-{idx}
 *
 * The dialog is opened from DashboardTabContent via data-testid="dashboard-export-btn".
 */
import { test, expect } from "../fixtures/links-page";

const FRONTEND_BASE = process.env.FRONTEND_BASE_URL ?? "http://localhost:3000";

test.describe("Export/Import Dialog", () => {
  test.beforeEach(async ({ page, resetLinks, seedLinks }) => {
    await resetLinks();
    await seedLinks("full");
    await page.goto(`${FRONTEND_BASE}/links?tab=dashboard`);
    await page.waitForLoadState("networkidle");
  });

  test("Dashboard export button opens dialog", async ({ page }) => {
    // The dashboard tab has a button with data-testid="dashboard-export-btn"
    const dashboardExportBtn = page.locator('[data-testid="dashboard-export-btn"]');
    await expect(dashboardExportBtn).toBeVisible({ timeout: 5_000 });
    await dashboardExportBtn.click();
    const dialog = page.locator('[data-testid="export-import-dialog"]');
    await expect(dialog).toBeVisible();
    // Verify the dialog contains the expected header text
    await expect(dialog).toContainText("Export / Import");
  });

  test("Dialog has Export and Import tabs", async ({ page }) => {
    await page.locator('[data-testid="dashboard-export-btn"]').click();
    const exportTab = page.locator('[data-testid="export-tab"]');
    const importTab = page.locator('[data-testid="import-tab"]');
    await expect(exportTab).toBeVisible();
    await expect(importTab).toBeVisible();
    // Verify tab text content
    await expect(exportTab).toHaveText("Export");
    await expect(importTab).toHaveText("Import");
  });

  test("Export tab shows format buttons for all formats", async ({ page }) => {
    await page.locator('[data-testid="dashboard-export-btn"]').click();
    // The component renders individual format buttons, not a single select
    const formats = ["csv", "jsonl", "json", "replay"];
    for (const fmt of formats) {
      const btn = page.locator(`[data-testid="export-format-${fmt}"]`);
      await expect(btn).toBeVisible();
    }
    // CSV should be selected by default (indicated by accent-blue styling)
    const csvBtn = page.locator('[data-testid="export-format-csv"]');
    await expect(csvBtn).toHaveClass(/border-accent-blue/);
  });

  test("Clicking a format button selects it", async ({ page }) => {
    await page.locator('[data-testid="dashboard-export-btn"]').click();
    const jsonlBtn = page.locator('[data-testid="export-format-jsonl"]');
    await jsonlBtn.click();
    // After clicking, JSONL button should have selected styling
    await expect(jsonlBtn).toHaveClass(/border-accent-blue/);
    // CSV button should no longer be selected
    const csvBtn = page.locator('[data-testid="export-format-csv"]');
    await expect(csvBtn).not.toHaveClass(/border-accent-blue/);
  });

  test("Export button is present and labelled correctly", async ({ page }) => {
    await page.locator('[data-testid="dashboard-export-btn"]').click();
    const exportBtn = page.locator('[data-testid="export-btn"]');
    await expect(exportBtn).toBeVisible();
    await expect(exportBtn).toHaveText("Export Links");
  });

  test("Import tab shows file dropzone and import button", async ({ page }) => {
    await page.locator('[data-testid="dashboard-export-btn"]').click();
    await page.locator('[data-testid="import-tab"]').click();
    const dropzone = page.locator('[data-testid="import-dropzone"]');
    await expect(dropzone).toBeVisible();
    // Dropzone should show instructions
    await expect(dropzone).toContainText("Drop file here or click to browse");
    // Import button should exist and be disabled (no file selected)
    const importBtn = page.locator('[data-testid="import-btn"]');
    await expect(importBtn).toBeVisible();
    await expect(importBtn).toBeDisabled();
    await expect(importBtn).toHaveText("Import Links");
  });

  test("Hidden file input accepts csv, jsonl, json", async ({ page }) => {
    await page.locator('[data-testid="dashboard-export-btn"]').click();
    await page.locator('[data-testid="import-tab"]').click();
    const fileInput = page.locator('[data-testid="import-file-input"]');
    // The input is hidden but present in the DOM
    await expect(fileInput).toBeAttached();
    await expect(fileInput).toHaveAttribute("accept", ".csv,.jsonl,.json");
  });

  test("Close button dismisses dialog", async ({ page }) => {
    await page.locator('[data-testid="dashboard-export-btn"]').click();
    const dialog = page.locator('[data-testid="export-import-dialog"]');
    await expect(dialog).toBeVisible();
    // The close button testid is "export-import-close"
    await page.locator('[data-testid="export-import-close"]').click();
    await expect(dialog).toBeHidden();
  });

  test("Clicking dialog backdrop dismisses dialog", async ({ page }) => {
    await page.locator('[data-testid="dashboard-export-btn"]').click();
    const dialog = page.locator('[data-testid="export-import-dialog"]');
    await expect(dialog).toBeVisible();
    // Click on the outer overlay (the dialog container itself acts as the backdrop)
    await dialog.click({ position: { x: 10, y: 10 } });
    await expect(dialog).toBeHidden();
  });

  test("Switching between Export and Import tabs", async ({ page }) => {
    await page.locator('[data-testid="dashboard-export-btn"]').click();
    // Initially on Export tab — format buttons should be visible
    await expect(page.locator('[data-testid="export-format-csv"]')).toBeVisible();
    await expect(page.locator('[data-testid="import-dropzone"]')).toBeHidden();

    // Switch to Import tab
    await page.locator('[data-testid="import-tab"]').click();
    await expect(page.locator('[data-testid="import-dropzone"]')).toBeVisible();
    await expect(page.locator('[data-testid="export-format-csv"]')).toBeHidden();

    // Switch back to Export tab
    await page.locator('[data-testid="export-tab"]').click();
    await expect(page.locator('[data-testid="export-format-csv"]')).toBeVisible();
  });
});

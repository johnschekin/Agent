/**
 * Reusable keyboard shortcut helpers for E2E tests.
 *
 * Maps domain keyboard shortcuts to Playwright key sequences.
 * Used primarily in Phase 3+ browser tests (Review tab navigation).
 */
import type { Page } from "@playwright/test";

/** Move focus down one row. */
export async function pressDown(page: Page): Promise<void> {
  await page.keyboard.press("j");
}

/** Move focus up one row. */
export async function pressUp(page: Page): Promise<void> {
  await page.keyboard.press("k");
}

/** Unlink the focused row. */
export async function pressUnlink(page: Page): Promise<void> {
  await page.keyboard.press("u");
}

/** Bookmark the focused row. */
export async function pressBookmark(page: Page): Promise<void> {
  await page.keyboard.press("b");
}

/** Toggle expand / preview. */
export async function pressExpand(page: Page): Promise<void> {
  await page.keyboard.press("Space");
}

/** Go back / close panel. */
export async function pressBack(page: Page): Promise<void> {
  await page.keyboard.press("Backspace");
}

/** Open the command palette. */
export async function openCommandPalette(page: Page): Promise<void> {
  const modifier = process.platform === "darwin" ? "Meta" : "Control";
  await page.keyboard.press(`${modifier}+k`);
}

/** Press Escape. */
export async function pressEscape(page: Page): Promise<void> {
  await page.keyboard.press("Escape");
}

/** Undo last action (Ctrl/Cmd+Z). */
export async function pressUndo(page: Page): Promise<void> {
  const modifier = process.platform === "darwin" ? "Meta" : "Control";
  await page.keyboard.press(`${modifier}+z`);
}

/** Redo last action (Ctrl/Cmd+Shift+Z). */
export async function pressRedo(page: Page): Promise<void> {
  const modifier = process.platform === "darwin" ? "Meta" : "Control";
  await page.keyboard.press(`${modifier}+Shift+z`);
}

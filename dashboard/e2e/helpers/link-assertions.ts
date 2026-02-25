/**
 * Custom assertion helpers for link E2E tests.
 *
 * Provides semantic assertion functions that make test expectations more
 * readable and produce better error messages.
 */
import { expect } from "@playwright/test";

/** Assert that a response is OK (2xx). */
export function expectOk(
  res: { ok: () => boolean; status: () => number },
): void {
  expect(res.ok(), `Expected 2xx, got ${res.status()}`).toBeTruthy();
}

/** Assert that a link object has all required fields. */
export function expectValidLink(link: Record<string, unknown>): void {
  expect(link).toHaveProperty("link_id");
  expect(link).toHaveProperty("family_id");
  expect(link).toHaveProperty("doc_id");
  expect(link).toHaveProperty("section_number");
  expect(link).toHaveProperty("status");
}

/** Assert that a list of links is sorted by the given field in descending order. */
export function expectSortedDesc(
  items: Record<string, unknown>[],
  field: string,
): void {
  for (let i = 1; i < items.length; i++) {
    const prev = items[i - 1][field] as number;
    const curr = items[i][field] as number;
    expect(prev).toBeGreaterThanOrEqual(curr);
  }
}

/** Assert that all items in a list match a predicate. */
export function expectAll<T>(
  items: T[],
  predicate: (item: T) => boolean,
  message?: string,
): void {
  const failing = items.filter((item) => !predicate(item));
  expect(
    failing.length,
    message ?? `Expected all ${items.length} items to pass, ${failing.length} failed`,
  ).toBe(0);
}

/** Assert that a response body has pagination metadata. */
export function expectPaginated(body: Record<string, unknown>): void {
  expect(body).toHaveProperty("total");
  expect(typeof body.total).toBe("number");
}

/** Assert confidence tier is valid. */
export function expectValidTier(tier: unknown): void {
  expect(["high", "medium", "low"]).toContain(tier);
}

/** Assert that a rule object has required fields. */
export function expectValidRule(rule: Record<string, unknown>): void {
  expect(rule).toHaveProperty("rule_id");
  expect(rule).toHaveProperty("family_id");
  expect(rule).toHaveProperty("heading_filter_ast");
  expect(rule).toHaveProperty("status");
}

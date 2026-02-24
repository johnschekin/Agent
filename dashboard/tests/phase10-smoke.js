const { chromium } = require("playwright");

const BASE = "http://localhost:3000";
const TIMEOUT = 15000;

async function run() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  let passed = 0;
  let failed = 0;

  async function check(name, fn) {
    const page = await context.newPage();
    try {
      await fn(page);
      console.log(`  ✓ ${name}`);
      passed++;
    } catch (err) {
      console.log(`  ✗ ${name}`);
      console.log(`    ${err.message.split("\n")[0]}`);
      failed++;
    } finally {
      await page.close();
    }
  }

  async function expectTextMatch(page, selector, pattern) {
    const el = await page.waitForSelector(selector, { timeout: TIMEOUT });
    const text = await el.textContent();
    if (!pattern.test(text)) {
      throw new Error(`Expected "${selector}" to match ${pattern}, got: "${text}"`);
    }
  }

  async function expectVisible(page, selector) {
    await page.waitForSelector(selector, { timeout: TIMEOUT, state: "visible" });
  }

  console.log("\nPhase 10 Smoke Tests — Review Operations\n");

  // 1. Review Home hub
  await check("Review Home page loads with title and KPI cards", async (page) => {
    await page.goto(`${BASE}/review`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Review Operations/);
    // KPI cards should render (Evidence Rows, Families, Stale Agents)
    await expectVisible(page, "text=Evidence Rows");
    await expectVisible(page, "text=Families");
    await expectVisible(page, "text=Stale Agents");
  });

  // 2. Review Home shows navigation cards for all 5 sub-views
  await check("Review Home has navigation links to all sub-views", async (page) => {
    await page.goto(`${BASE}/review`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectVisible(page, 'a[href="/review/strategy"]');
    await expectVisible(page, 'a[href="/review/evidence"]');
    await expectVisible(page, 'a[href="/review/coverage"]');
    await expectVisible(page, 'a[href="/review/judge"]');
    await expectVisible(page, 'a[href="/review/activity"]');
  });

  // 3. Strategy Timeline page
  await check("Strategy Timeline page loads with concept input", async (page) => {
    await page.goto(`${BASE}/review/strategy`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Review: Strategy Timeline/);
    // Should have a concept_id input
    await expectVisible(page, 'input[placeholder="concept_id"]');
  });

  // 4. Evidence Browser page
  await check("Evidence Browser page loads with filters and data", async (page) => {
    await page.goto(`${BASE}/review/evidence`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Review: Evidence Browser/);
    // Filter controls
    await expectVisible(page, 'input[placeholder="concept_id"]');
    await expectVisible(page, 'input[placeholder="template_family"]');
    // Record type selector
    const selectCount = await page.locator("select").count();
    if (selectCount < 2) {
      throw new Error(`Expected at least 2 selects (record type + limit), got ${selectCount}`);
    }
    // Reset button
    await expectVisible(page, 'button >> text="Reset"');
    // Wait for data table to appear (evidence exists in workspace)
    await page.waitForSelector("table", { timeout: TIMEOUT });
    // Verify pagination metadata renders
    await expectVisible(page, "text=Returned");
  });

  // 5. Evidence Browser pagination controls
  await check("Evidence Browser has Prev/Next pagination", async (page) => {
    await page.goto(`${BASE}/review/evidence`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await page.waitForSelector("table", { timeout: TIMEOUT });
    await expectVisible(page, 'button >> text="Prev"');
    await expectVisible(page, 'button >> text="Next"');
  });

  // 6. Coverage Heatmap page
  await check("Coverage Heatmap page loads with matrix", async (page) => {
    await page.goto(`${BASE}/review/coverage`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Review: Coverage Heatmap/);
    // Should render a table (the matrix)
    await page.waitForSelector("table", { timeout: TIMEOUT });
  });

  // 7. Judge History page
  await check("Judge History page loads with concept input", async (page) => {
    await page.goto(`${BASE}/review/judge`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Review: (LLM )?Judge History/);
    await expectVisible(page, 'input[placeholder="concept_id"]');
  });

  // 8. Agent Activity page
  await check("Agent Activity page loads with KPI cards and agent table", async (page) => {
    await page.goto(`${BASE}/review/activity`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Review: Agent Activity/);
    // KPI cards
    await expectVisible(page, "text=Agents");
    await expectVisible(page, "text=Stale Agents");
    await expectVisible(page, "text=Stale Threshold");
    // Stale threshold selector
    await expectVisible(page, "select");
    // Agent table should render (49 family workspaces exist)
    await page.waitForSelector("table", { timeout: TIMEOUT });
  });

  // 9. Agent Activity stale-threshold dropdown works
  await check("Agent Activity stale threshold changes", async (page) => {
    await page.goto(`${BASE}/review/activity`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await page.waitForSelector("table", { timeout: TIMEOUT });
    // Change threshold to 15 min
    await page.selectOption("select", "15");
    // Wait for refetch
    await page.waitForTimeout(1000);
    // Table should still be visible
    await expectVisible(page, "table");
  });

  // 10. Spot-check that Phase 9 pages still render (regression guard)
  await check("Strategy Manager still renders (regression)", async (page) => {
    await page.goto(`${BASE}/strategies`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Strategy Manager/);
  });

  console.log(`\nResult: ${passed} passed, ${failed} failed\n`);

  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});

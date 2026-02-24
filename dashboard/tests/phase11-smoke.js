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

  console.log("\nPhase 11 Smoke Tests — ML & Learning\n");

  // 1. Review Queue page loads with title and KPI cards
  await check("Review Queue page loads with title and KPIs", async (page) => {
    await page.goto(`${BASE}/ml/review`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Review Queue/);
    await expectVisible(page, "text=Total Queue");
    await expectVisible(page, "text=High Priority");
    await expectVisible(page, "text=Medium Priority");
  });

  // 2. Review Queue has filter controls
  await check("Review Queue has filter controls", async (page) => {
    await page.goto(`${BASE}/ml/review`, { waitUntil: "networkidle", timeout: TIMEOUT });
    // Priority dropdown, concept input, template input, limit dropdown, Reset button
    await expectVisible(page, 'input[placeholder="concept_id"]');
    await expectVisible(page, 'input[placeholder="template_family"]');
    await expectVisible(page, 'button >> text="Reset"');
    const selectCount = await page.locator("select").count();
    if (selectCount < 2) {
      throw new Error(`Expected at least 2 selects (priority + limit), got ${selectCount}`);
    }
  });

  // 3. Review Queue shows table with evidence data
  await check("Review Queue shows table with data", async (page) => {
    await page.goto(`${BASE}/ml/review`, { waitUntil: "networkidle", timeout: TIMEOUT });
    // Wait for table to appear (evidence exists in workspaces)
    await page.waitForSelector("table", { timeout: TIMEOUT });
    // Should have pagination controls
    await expectVisible(page, 'button >> text="Prev"');
    await expectVisible(page, 'button >> text="Next"');
    // Should show "Showing" metadata
    await expectVisible(page, "text=Showing");
  });

  // 4. Review Queue row expands on click
  await check("Review Queue row expands on click", async (page) => {
    await page.goto(`${BASE}/ml/review`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await page.waitForSelector("table tbody tr", { timeout: TIMEOUT });
    // Click the first data row
    await page.click("table tbody tr:first-child");
    await page.waitForTimeout(500);
    // Expanded detail should show confidence breakdown
    await expectVisible(page, "text=Confidence Breakdown");
    await expectVisible(page, "text=Review Reasons");
  });

  // 5. Clause Clusters page loads with concept selector
  await check("Clause Clusters page loads with concept selector", async (page) => {
    await page.goto(`${BASE}/ml/clusters`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Clause Clusters/);
    // Should have concept selector
    await expectVisible(page, "select");
  });

  // 6. Clause Clusters shows empty state before selection
  await check("Clause Clusters shows empty state before selection", async (page) => {
    await page.goto(`${BASE}/ml/clusters`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectVisible(page, 'h3:has-text("Select a Concept")');
  });

  // 7. Clause Clusters shows data after concept selection
  await check("Clause Clusters shows clusters after concept selection", async (page) => {
    await page.goto(`${BASE}/ml/clusters`, { waitUntil: "networkidle", timeout: TIMEOUT });
    // Wait for concept dropdown to be populated (concepts-with-evidence API must return)
    await page.waitForFunction(
      () => document.querySelectorAll("select option").length > 1,
      { timeout: TIMEOUT }
    );
    // Select the first real concept option
    const firstVal = await page.locator("select option").nth(1).getAttribute("value");
    if (!firstVal) throw new Error("No concept value in dropdown option");
    await page.locator("select").selectOption(firstVal);
    // Wait for clusters table to appear (heading-clusters API must return)
    await page.waitForSelector("table", { timeout: TIMEOUT });
    // Should show KPI cards
    await expectVisible(page, 'text="Total Clusters"');
    await expectVisible(page, 'text="Known Headings"');
    await expectVisible(page, 'text="Unknown Headings"');
  });

  // 8. Regression: Phase 9 Strategy Manager still renders
  await check("Strategy Manager still renders (regression)", async (page) => {
    await page.goto(`${BASE}/strategies`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Strategy Manager/);
  });

  // 9. Regression: Phase 10 Review Home still renders
  await check("Review Operations still renders (regression)", async (page) => {
    await page.goto(`${BASE}/review`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Review Operations/);
  });

  console.log(`\nResult: ${passed} passed, ${failed} failed\n`);

  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});

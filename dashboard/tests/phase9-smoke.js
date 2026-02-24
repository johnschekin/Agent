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

  console.log("\nPhase 9 Smoke Tests\n");

  // 1. Strategy Manager
  await check("Strategy Manager page loads with title and filters", async (page) => {
    await page.goto(`${BASE}/strategies`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Strategy Manager/);
    await expectVisible(page, 'input[placeholder="Search concepts..."]');
  });

  // 2. Strategy Results
  await check("Strategy Results page loads", async (page) => {
    await page.goto(`${BASE}/strategies/results`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Strategy Results/);
    // May show loading or results depending on API; just confirm title renders
  });

  // 3. Feedback Backlog
  await check("Feedback Backlog page loads with New Feedback button", async (page) => {
    await page.goto(`${BASE}/feedback`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Feedback Backlog/);
    await expectVisible(page, 'button >> text="+ New Feedback"');
  });

  // 4. Feedback create form
  await check("Feedback create form opens and closes", async (page) => {
    await page.goto(`${BASE}/feedback`, { waitUntil: "networkidle", timeout: TIMEOUT });
    // Find and click the "New Feedback" button
    await page.locator("button", { hasText: "New Feedback" }).click({ timeout: TIMEOUT });
    await page.waitForTimeout(1000);
    // Take debug screenshot
    await page.screenshot({ path: "/tmp/feedback-debug.png" });
    // Check what's on the page
    const html = await page.content();
    const hasBriefDesc = html.includes("Brief description");
    const hasNewFeedbackItem = html.includes("New Feedback Item");
    if (!hasBriefDesc && !hasNewFeedbackItem) {
      throw new Error("Form did not appear after clicking New Feedback button");
    }
    // If we got here, form appeared
    // Click Cancel
    await page.locator("button", { hasText: "Cancel" }).click({ timeout: 5000 });
    await page.waitForTimeout(500);
  });

  // 5. Spot check existing pages
  await check("Reader page renders", async (page) => {
    await page.goto(`${BASE}/reader`, { waitUntil: "networkidle", timeout: TIMEOUT });
    // Reader page has a label "Document:" in the header
    await expectVisible(page, 'label[for="doc-picker"]');
  });

  await check("Ontology page renders", async (page) => {
    await page.goto(`${BASE}/ontology`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Ontology Explorer/);
  });

  await check("Explorer page renders", async (page) => {
    await page.goto(`${BASE}/explorer`, { waitUntil: "networkidle", timeout: TIMEOUT });
    await expectTextMatch(page, "h2", /Document Explorer/);
  });

  console.log(`\nResult: ${passed} passed, ${failed} failed\n`);

  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});

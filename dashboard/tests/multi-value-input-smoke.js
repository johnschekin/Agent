const { chromium } = require("playwright");

const BASE = "http://localhost:3000";
const TIMEOUT = 30000;

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

  console.log("\nMulti-Value Input Smoke Tests\n");

  // 1. Page loads with Corpus Query Builder title
  await check("Corpus Query page loads", async (page) => {
    await page.goto(`${BASE}/corpus/query`, { waitUntil: "networkidle", timeout: TIMEOUT });
    const h2 = await page.waitForSelector("h2", { timeout: TIMEOUT });
    const text = await h2.textContent();
    if (!/Corpus Query Builder/.test(text)) {
      throw new Error(`Expected title "Corpus Query Builder", got: "${text}"`);
    }
  });

  // 2. Multi-value inputs exist (check aria-labels)
  await check("Multi-value inputs are present for all 4 filter fields", async (page) => {
    await page.goto(`${BASE}/corpus/query`, { waitUntil: "networkidle", timeout: TIMEOUT });

    const ariaLabels = [
      "Article title filters",
      "Section heading filters",
      "Clause text filters",
      "Clause header filters",
    ];

    for (const label of ariaLabels) {
      const input = await page.waitForSelector(`input[aria-label="${label}"]`, { timeout: TIMEOUT });
      if (!input) {
        throw new Error(`Missing multi-value input with aria-label="${label}"`);
      }
    }
  });

  // 3. Typing + Enter creates a chip
  await check("Typing + Enter creates a chip with × button", async (page) => {
    await page.goto(`${BASE}/corpus/query`, { waitUntil: "networkidle", timeout: TIMEOUT });

    const input = await page.waitForSelector('input[aria-label="Article title filters"]', { timeout: TIMEOUT });
    await input.click();
    await input.type("%debt%");
    await input.press("Enter");

    // Wait for chip to appear — look for the × remove button
    await page.waitForSelector('button[aria-label="Remove %debt%"]', { timeout: 5000 });

    // The input draft should be cleared
    const inputValue = await input.inputValue();
    if (inputValue !== "") {
      throw new Error(`Expected input to be cleared after Enter, got: "${inputValue}"`);
    }
  });

  // 4. Adding a second chip shows an operator badge
  await check("Second chip shows operator badge (OR by default)", async (page) => {
    await page.goto(`${BASE}/corpus/query`, { waitUntil: "networkidle", timeout: TIMEOUT });

    const input = await page.waitForSelector('input[aria-label="Section heading filters"]', { timeout: TIMEOUT });

    // Add first chip
    await input.click();
    await input.type("%debt%");
    await input.press("Enter");
    await page.waitForSelector('button[aria-label="Remove %debt%"]', { timeout: 5000 });

    // Add second chip
    await input.type("%loan%");
    await input.press("Enter");
    await page.waitForSelector('button[aria-label="Remove %loan%"]', { timeout: 5000 });

    // The second chip should have an operator badge — look for button with text "OR"
    // The operator badge is a <button> with title containing "cycle"
    const opBadge = await page.waitForSelector('button[title*="Click to cycle"]', { timeout: 5000 });
    const opText = await opBadge.textContent();
    if (opText !== "OR") {
      throw new Error(`Expected operator badge "OR", got: "${opText}"`);
    }
  });

  // 5. Clicking operator badge cycles through operators
  await check("Clicking operator badge cycles OR → AND → NOT → AND NOT", async (page) => {
    await page.goto(`${BASE}/corpus/query`, { waitUntil: "networkidle", timeout: TIMEOUT });

    const input = await page.waitForSelector('input[aria-label="Clause text filters"]', { timeout: TIMEOUT });

    // Add two chips
    await input.click();
    await input.type("payment");
    await input.press("Enter");
    await page.waitForSelector('button[aria-label="Remove payment"]', { timeout: 5000 });

    await input.type("interest");
    await input.press("Enter");
    await page.waitForSelector('button[aria-label="Remove interest"]', { timeout: 5000 });

    const opBadge = await page.waitForSelector('button[title*="Click to cycle"]', { timeout: 5000 });

    // Default: OR
    let text = await opBadge.textContent();
    if (text !== "OR") throw new Error(`Expected "OR", got: "${text}"`);

    // Click → AND
    await opBadge.click();
    text = await opBadge.textContent();
    if (text !== "AND") throw new Error(`Expected "AND" after 1st click, got: "${text}"`);

    // Click → NOT
    await opBadge.click();
    text = await opBadge.textContent();
    if (text !== "NOT") throw new Error(`Expected "NOT" after 2nd click, got: "${text}"`);

    // Click → AND NOT
    await opBadge.click();
    text = await opBadge.textContent();
    if (text !== "AND NOT") throw new Error(`Expected "AND NOT" after 3rd click, got: "${text}"`);

    // Click → back to OR
    await opBadge.click();
    text = await opBadge.textContent();
    if (text !== "OR") throw new Error(`Expected "OR" after 4th click, got: "${text}"`);
  });

  // 6. × button removes a chip
  await check("Clicking × removes the chip", async (page) => {
    await page.goto(`${BASE}/corpus/query`, { waitUntil: "networkidle", timeout: TIMEOUT });

    const input = await page.waitForSelector('input[aria-label="Clause header filters"]', { timeout: TIMEOUT });
    await input.click();
    await input.type("test-chip");
    await input.press("Enter");

    const removeBtn = await page.waitForSelector('button[aria-label="Remove test-chip"]', { timeout: 5000 });
    await removeBtn.click();

    // Chip should be gone
    const removed = await page.$('button[aria-label="Remove test-chip"]');
    if (removed) {
      throw new Error("Chip was not removed after clicking ×");
    }
  });

  // 7. Backspace on empty input removes last chip
  await check("Backspace on empty input removes last chip", async (page) => {
    await page.goto(`${BASE}/corpus/query`, { waitUntil: "networkidle", timeout: TIMEOUT });

    const input = await page.waitForSelector('input[aria-label="Article title filters"]', { timeout: TIMEOUT });
    await input.click();

    // Add a chip
    await input.type("remove-me");
    await input.press("Enter");
    await page.waitForSelector('button[aria-label="Remove remove-me"]', { timeout: 5000 });

    // Input should be empty now — press Backspace to remove chip
    await input.press("Backspace");

    // Chip should be gone
    const removed = await page.$('button[aria-label="Remove remove-me"]');
    if (removed) {
      throw new Error("Chip was not removed after Backspace on empty input");
    }
  });

  console.log(`\nResult: ${passed} passed, ${failed} failed\n`);

  await browser.close();
  process.exit(failed > 0 ? 1 : 0);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});

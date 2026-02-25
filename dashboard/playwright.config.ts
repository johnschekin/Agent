import { defineConfig, devices } from "@playwright/test";

const FRONTEND_BASE_URL =
  process.env.FRONTEND_BASE_URL ?? "http://127.0.0.1:3100";
const API_BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8100";

process.env.FRONTEND_BASE_URL = FRONTEND_BASE_URL;
process.env.API_BASE_URL = API_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // Serial within file (shared DB state)
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1, // Single worker — DuckDB is single-writer
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "on-failure" }]],
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: FRONTEND_BASE_URL,
    trace: process.env.CI ? "on-first-retry" : "retain-on-failure",
    screenshot: "only-on-failure",
    video: process.env.CI ? "off" : "retain-on-failure",
    actionTimeout: 8_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    ...(process.env.CI
      ? [
          { name: "firefox", use: { ...devices["Desktop Firefox"] } },
          { name: "webkit", use: { ...devices["Desktop Safari"] } },
        ]
      : []),
  ],
  webServer: [
    {
      command:
        "LINKS_TEST_MODE=1 LINKS_API_TOKEN=local-dev-links-token LINKS_ADMIN_TOKEN=local-dev-links-token LINKS_TEST_ENDPOINT_TOKEN=local-dev-links-token python3 -m uvicorn dashboard.api.server:app --host 127.0.0.1 --port 8100",
      url: `${API_BASE_URL}/api/health`,
      cwd: "..",
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: `NEXT_PUBLIC_API_URL=${API_BASE_URL} NEXT_PUBLIC_LINKS_API_TOKEN=local-dev-links-token npm run dev -- --hostname 127.0.0.1 --port 3100`,
      url: `${FRONTEND_BASE_URL}/links`,
      cwd: ".",
      timeout: 180_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});

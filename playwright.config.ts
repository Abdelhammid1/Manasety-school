import { defineConfig, devices } from '@playwright/test';

/**
 * Sprint 9 QA sweep — Playwright e2e config.
 * Runs the reproduction steps from the client's Bug Report PDF one by one.
 * Assumes Flask is already running on localhost:5050 (see scripts/run-audit.sh).
 */
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false, // shared session state
  retries: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: 'http://localhost:5050',
    locale: 'ar',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // Chromium is what we installed; headless by default (set HEADED=1 to see it)
    headless: !process.env.HEADED,
    ignoreHTTPSErrors: true,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
});

import { defineConfig, devices } from '@playwright/test'

// Runs specs against a deployed site: BASE_URL=https://... npx playwright test -c playwright.deployed.config.ts
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  use: {
    baseURL: process.env.BASE_URL,
    headless: true,
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } } : { channel: 'chromium' }),
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})

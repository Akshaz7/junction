import { defineConfig, devices } from '@playwright/test'

const finalRun = process.env.E2E_FINAL === '1'
const port = process.env.PW_PORT ?? '5173'
const baseURL = process.env.E2E_BASE ?? `http://localhost:${port}`
const run = process.env.E2E_RUN_ID ?? 'local'

export default defineConfig({
  testDir: './e2e',
  ...(finalRun ? {
    testMatch: /final-.*\.spec\.ts/,
    outputDir: `../results/final/E2E/${run}/artifacts`,
    reporter: [['list'], ['./e2e/final-reporter.ts']],
  } : {}),
  fullyParallel: false,
  workers: 1,
  timeout: 15_000,
  use: {
    baseURL,
    headless: true,
    ...(finalRun ? { trace: 'retain-on-failure' as const, screenshot: 'only-on-failure' as const, actionTimeout: 15_000 } : {}),
    // LEAD 07:35: real GPU (Metal) — SwiftShader starved the main thread with two 3D pages open (4.1 s vs 0.8 s).
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } } : { channel: 'chromium', launchOptions: { args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-gpu'] } }),
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: finalRun ? undefined : {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: true,
    timeout: 20_000,
  },
})

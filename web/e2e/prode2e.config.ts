import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: '.',
  testMatch: 'prode2e-calculation.spec.ts',
  workers: 1,
  timeout: 120_000,
  reporter: 'list',
  outputDir: '../../results/final/PRODE2E/test-artifacts',
  use: {
    headless: true,
    viewport: { width: 1440, height: 1000 },
    channel: 'chromium',
    launchOptions: { args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-gpu'] },
  },
})

import { defineConfig, devices } from '@playwright/test'

const port = process.env.PW_PORT ?? '5173'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 15_000,
  use: {
    baseURL: `http://localhost:${port}`,
    headless: true,
    // LEAD 07:35: real GPU (Metal) — SwiftShader starved the main thread with two 3D pages open (4.1 s vs 0.8 s).
    ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? { launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH } } : { channel: 'chromium', launchOptions: { args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-gpu'] } }),
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: `npm run dev -- --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://localhost:${port}`,
    reuseExistingServer: true,
    timeout: 20_000,
  },
})

import { defineConfig } from '@playwright/test'
// Dedicated port; this worker never starts the shared development stack.
export default defineConfig({
  testDir: './e2e', testMatch: 'sheet-overlay.spec.ts', workers: 1, fullyParallel: false, timeout: 60_000,
  use: { baseURL: 'http://127.0.0.1:5367', headless: true, viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' },
  webServer: { command: 'VITE_USE_MOCK=false npm run dev -- --host 127.0.0.1 --port 5367 --strictPort', url: 'http://127.0.0.1:5367', reuseExistingServer: false, timeout: 20_000 },
})

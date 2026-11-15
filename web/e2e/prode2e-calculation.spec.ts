import { expect, test } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'
import { basename, resolve } from 'node:path'

// Read-only replay of real smoke-test answers, with this branch's built frontend.
// npm run build; ../scripts/heavy.sh npx playwright test -c e2e/prode2e.config.ts
const output = resolve('../results/final/PRODE2E')
const casesFile = process.env.PRODE2E_CASES ?? resolve(output, 'calculation-cases.json')

test('real calculations load source drawings without flooding page-image requests', async ({ page }) => {
  const cases = JSON.parse(await readFile(casesFile, 'utf8')) as { name: string; url: string; projectUrl?: string }[]
  const results: Record<string, unknown>[] = []
  // Keep the production backend and source files; serve only the built HTML/JS/CSS locally.
  await page.route('**/*', async (route) => {
    const url = new URL(route.request().url())
    const file = url.pathname.startsWith('/assets/') ? resolve('dist/assets', basename(url.pathname))
      : route.request().isNavigationRequest() && url.pathname === '/' ? resolve('dist/index.html') : null
    if (!file) return route.continue()
    await route.fulfill({ path: file })
  })
  for (const row of cases) {
    const images: Record<string, number> = {}, errors: string[] = []
    const request = (r: { url: () => string }) => {
      const path = new URL(r.url()).pathname
      if (/\/pages\/\d+\/image$/.test(path)) images[path] = (images[path] ?? 0) + 1
    }
    const consoleError = (m: { type: () => string; text: () => string }) => { if (m.type() === 'error') errors.push(m.text()) }
    page.on('request', request)
    page.on('console', consoleError)
    try {
      await page.goto(row.url)
      const card = page.getByTestId('answer-card').first()
      await card.getByRole('button', { name: 'Show calculation', exact: true }).click()
      await expect(page.getByTestId('calc-panel')).toBeVisible()
      await expect(page.locator('.drawing-plane > img')).toBeVisible()
      await expect.poll(() => page.locator('.drawing-plane > img').evaluate((node) => (node as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
      await expect.poll(() => page.locator('canvas.calc-crop').evaluateAll((nodes) => nodes.filter((node) => (node as HTMLCanvasElement).width !== 300).length)).toBeGreaterThan(0)
      await page.screenshot({ path: resolve(output, `fixed-${row.name}.png`) })
      // One drawing request and at most one shared crop request per source page.
      expect(Object.values(images).every((count) => count <= 2), JSON.stringify(images)).toBe(true)
      expect(errors.filter((text) => /INSUFFICIENT_RESOURCES|Failed to fetch/.test(text))).toEqual([])
      results.push({ ...row, status: 'PASS', image_requests: images, console_errors: errors, crops: await page.locator('canvas.calc-crop').count() })
    } catch (error) {
      results.push({ ...row, status: 'FAIL', image_requests: images, console_errors: errors, error: String(error) })
      throw error
    } finally {
      page.off('request', request)
      page.off('console', consoleError)
      await writeFile(resolve(output, 'calculation-regression.json'), JSON.stringify(results, null, 2))
    }
  }
  const projectUrl = cases.find((row) => row.projectUrl)?.projectUrl
  if (projectUrl) {
    await page.goto(projectUrl)
    const tiles = page.getByRole('complementary', { name: 'Project content', exact: true }).locator('.pj-tile img')
    await expect(tiles.first()).toBeVisible()
    await expect.poll(() => tiles.evaluateAll((nodes) => nodes.filter((node) => (node as HTMLImageElement).naturalWidth > 0).length)).toBeGreaterThan(0)
    expect(await tiles.evaluateAll((nodes) => nodes.some((node) => /\/pages\/\d+\.png$/.test((node as HTMLImageElement).src)))).toBe(false)
    await page.screenshot({ path: resolve(output, 'fixed-project-thumbnails.png') })
  }
})

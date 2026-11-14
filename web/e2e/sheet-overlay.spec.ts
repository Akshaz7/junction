import { test, expect, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { type Alignment, type OverlayDoc } from '../src/lib/sheet-overlay'

const root = resolve(import.meta.dirname, '../..'), output = resolve(root, 'results/final/OVERLAY')
const alignment: Alignment = JSON.parse(readFileSync(resolve(output, '.local/judges-alignment.json'), 'utf8'))
const docs: OverlayDoc[] = [
  { doc_id: 'test-arch', title: 'Architecture · third floor', source: 'Judges', formats: ['pdf'], kind: 'pdf', pages: 1, licence: 'Private judging material', credit: 'Provided by judges', heldout: true, project: 'Judges building', floor: '3', discipline: 'Architecture' },
  { doc_id: 'test-vent', title: 'Ventilation · third floor · Block U', source: 'Judges', formats: ['pdf'], kind: 'pdf', pages: 1, licence: 'Private judging material', credit: 'Provided by judges', heldout: true, project: 'Judges building', floor: '3', discipline: 'Ventilation' },
]

async function sources(page: Page, needsManual = false) {
  // Browser transport fixture uses real source images and the real engine's computed matrix.
  // It creates no chats, uploads or files in shared services.
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname
    if (path === '/api/docs') return route.fulfill({ json: { total: 2, sources: [{ source: 'Judges', docs }] } })
    if (/\/pages\/1\/image$/.test(path)) return route.fulfill({ contentType: 'image/png', body: readFileSync(resolve(root, path.includes('test-arch') ? 'data/judges/p1.png' : 'data/judges/p0.png')) })
    if (path === '/api/sheet-align') {
      const body = route.request().postDataJSON()
      if (body.base_points) {
        const [p,q] = body.base_points, [a,b] = body.overlay_points
        const dx=b[0]-a[0], dy=b[1]-a[1], den=dx*dx+dy*dy
        const u=((q[0]-p[0])*dx+(q[1]-p[1])*dy)/den, v=((q[1]-p[1])*dx-(q[0]-p[0])*dy)/den
        return route.fulfill({ json: { ...alignment, status: 'manual', method: 'two-point', residual_mm: null, residual_px: null, matrix: [[u,-v,p[0]-u*a[0]+v*a[1]],[v,u,p[1]-v*a[0]-u*a[1]]], detail: 'Manually aligned on 2 points. Check a third crossing before relying on it.' } })
      }
      return route.fulfill({ json: needsManual ? { ...alignment, status: 'needs_manual', matrix: null, detail: 'Too few shared labels. Choose the same two grid crossings on both sheets.' } : alignment })
    }
    const doc = docs.find((d) => path === `/api/docs/${d.doc_id}`)
    if (doc) return route.fulfill({ json: doc })
    if (path.endsWith('/scene.json')) return route.fulfill({ json: { items: {} } })
    if (path.includes('/planmap/')) return route.fulfill({ json: { items: [], page: 1 } })
    if (path === '/api/chats') return route.fulfill({ json: { chats: [] } })
    if (path === '/api/changes') return route.fulfill({ json: { changes: [] } })
    return route.fulfill({ json: {} })
  })
  await page.goto('/#/chat')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill('overlay the ventilation plan on the floor plan')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Overlay sheets' })).toBeVisible()
  await expect(page.getByTestId('alignment-status')).toBeVisible()
}

async function waitCanvas(page: Page) {
  await expect(page.locator('.overlay-compare .sc-curr img')).toBeVisible()
  await expect.poll(() => page.locator('.overlay-compare .sc-curr img').evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0)).toBe(true)
  await expect(page.getByText('Checking shared drawing anchors…')).toHaveCount(0)
}

test('judges sheets: chat, aligned overlay, modes, opacity, layers and locked zoom', async ({ page }) => {
  await sources(page); await waitCanvas(page)
  await expect(page.getByTestId('alignment-status')).toContainText(`Aligned on ${alignment.anchor_count} shared labels`)
  await page.screenshot({ path: resolve(output, 'judges-overlay-desktop.png') })
  await page.getByRole('button', { name: 'Zoom in comparison' }).click()
  await expect.poll(async () => {
    const transforms = await page.locator('.overlay-compare .sc-sheet').evaluateAll((els) => els.map((el) => (el as HTMLElement).style.transform))
    return transforms.length === 2 && transforms[0] === transforms[1]
  }).toBe(true)
  await page.getByRole('slider', { name: 'Overlay opacity' }).fill('75')
  await expect(page.locator('.sc-curr')).toHaveCSS('opacity', '0.75')
  await page.getByRole('checkbox', { name: 'Base · grey' }).uncheck()
  await expect(page.locator('.sc-prev')).toHaveCSS('visibility', 'hidden')
  await page.getByRole('checkbox', { name: 'Base · grey' }).check()
  await page.getByRole('button', { name: 'Wipe', exact: true }).click()
  const seam = page.getByRole('slider', { name: 'Wipe position' }); await seam.focus(); await seam.press('Home'); await seam.press('ArrowRight')
  await expect(seam).toHaveAttribute('aria-valuenow', '1')
  await seam.press('End'); await seam.press('ArrowLeft', { delay: 30 })
  await page.getByRole('button', { name: 'Fit comparison' }).click()
  await page.screenshot({ path: resolve(output, 'judges-wipe-desktop.png') })
  await page.getByRole('button', { name: 'Plain', exact: true }).click()
  await expect(page.locator('.sc-prev')).toHaveCSS('visibility', 'hidden')
  await page.getByRole('button', { name: 'Close overlay' }).click()
  await expect(page.getByRole('button', { name: 'Overlay with…' })).toBeVisible()
  await page.getByRole('button', { name: 'Overlay with…' }).click()
  await expect(page.getByRole('heading', { name: 'Overlay sheets' })).toBeVisible()
})

test('phone: real aligned sheets, side-by-side with linked view, no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await sources(page); await waitCanvas(page)
  await page.screenshot({ path: resolve(output, 'judges-overlay-phone.png') })
  await page.getByRole('button', { name: 'Side by side', exact: true }).click()
  const pair = page.getByLabel('Sheets with linked zoom and pan')
  await expect(pair).toBeVisible()
  await pair.getByRole('button', { name: /Zoom in Architecture/ }).click()
  const views = await pair.locator('svg').evaluateAll((els) => els.map((s) => s.getAttribute('viewBox')))
  expect(views[0]).toBe(views[1])
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: resolve(output, 'judges-side-by-side-phone.png') })
})

test('insufficient anchors: honest status, two-point picking, manual fit without precision claim', async ({ page }) => {
  await sources(page, true)
  await expect(page.getByTestId('alignment-status')).toContainText('Too few shared labels')
  await expect(page.locator('.overlay-compare')).toHaveCount(0)
  await page.getByRole('button', { name: 'Align with two points' }).click()
  for (const name of ['Base alignment points', 'Overlay alignment points']) {
    const svg = page.getByRole('img', { name, exact: true }); const box = await svg.boundingBox(); expect(box).toBeTruthy()
    await svg.click({ position: { x: box!.width*.3, y: box!.height*.4 } })
    await svg.click({ position: { x: box!.width*.6, y: box!.height*.6 } })
  }
  await expect(page.getByRole('button', { name: 'Apply alignment' })).toBeEnabled()
  await page.getByRole('button', { name: 'Apply alignment' }).click(); await waitCanvas(page)
  await expect(page.getByTestId('alignment-status')).toContainText('Manually aligned on 2 points')
  await expect(page.getByTestId('alignment-status')).not.toContainText('mm')
})

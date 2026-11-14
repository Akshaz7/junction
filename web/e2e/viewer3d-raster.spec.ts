import { expect, test } from '@playwright/test'
import type { Viewer } from '../src/viewer3d/viewer'

// Raster plan 3D in the real viewer: dollhouse framing, tints, approx note, answer glow.
test.setTimeout(150_000)
for (const doc of ['cubicasa5k__high-quality-10306', 'cubicasa5k__colorful-11397', 'cubicasa5k__colorful-12200']) {
  test(`raster 3D ${doc}`, async ({ page }, testInfo) => {
    await page.goto(`/?doc=${doc}&viewer3dTest=1#/viewer-test`)
    await expect(page.getByRole('region', { name: '3D viewer', exact: true }).first()).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
    await page.waitForTimeout(3000)
    await page.screenshot({ path: testInfo.outputPath('plain.png') })
    const lit = await page.evaluate(() => {
      const v = (window as unknown as { viewer3dTest: Viewer }).viewer3dTest
      const ids = Object.entries(v.scene!.manifest.items).filter(([, i]) => i.kind === 'door' || i.kind === 'window').map(([id]) => id)
      v.highlight(ids); return ids.length
    })
    console.log(doc, 'lit', lit, 'approx-note', await page.locator('text=/approximated from the drawing/i').count())
    await page.waitForTimeout(2500)
    await page.screenshot({ path: testInfo.outputPath('lit.png') })
  })
}

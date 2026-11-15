import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'
import type { Viewer } from '../src/viewer3d/viewer'

// Real source artifacts and the real linked-route response captured by
// engine.tests.run_wall_details_audit. Isolated from the shared API and DB.
for (const docId of ['ifc_bench__ac20-arc', 'cubicasa5k__colorful-12200']) {
  test(`wall detail callout uses linked measurements after loading basic scene metadata: ${docId}`, async ({ page }) => {
    test.setTimeout(60_000)
    await page.setViewportSize({ width: 1440, height: 1200 })
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.routeWebSocket('**/ws*', () => {})
    const root = path.resolve('..')
    const artifact = docId.startsWith('ifc') ? path.join(root, 'artifacts', docId)
      : JSON.parse(await readFile(path.join(root, 'results/final/WALLPANEL', `${docId}.scratch.json`), 'utf8')).artifacts
    const detail = JSON.parse(await readFile(path.join(root, 'results/final/WALLPANEL', `${docId}.${docId.startsWith('ifc') ? 'item' : 'regenerated.item'}.json`), 'utf8'))
    const document = JSON.parse(await readFile(path.join(artifact, 'doc.json'), 'utf8'))
    let detailRequests = 0
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url())
      const prefix = `/api/docs/${docId}`
      if (url.pathname === '/api/docs') return route.fulfill({ json: { sources: [{ source: document.source, docs: [document] }], total: 1 } })
      if (url.pathname === `${prefix}/scene`) return route.fulfill({ path: path.join(artifact, 'scene.json'), contentType: 'application/json' })
      if (url.pathname === `${prefix}/files/scene.glb`) return route.fulfill({ path: path.join(artifact, 'scene.glb'), contentType: 'model/gltf-binary' })
      if (url.pathname === `${prefix}/files/elements.json` && docId.startsWith('ifc')) return route.fulfill({ path: path.join(artifact, 'elements.json'), contentType: 'application/json' })
      if (decodeURIComponent(url.pathname) === `${prefix}/items/${detail.item_id}`) {
        detailRequests++
        return route.fulfill({ json: detail })
      }
      return route.fulfill({ status: 404, json: { detail: 'Isolated read-only wall test' } })
    })
    await page.goto(`/?doc=${docId}&viewer3dTest=1#/viewer-test`)
    const region = page.getByRole('region', { name: '3D viewer', exact: true })
    await expect(region).toHaveAttribute('data-state', 'ready')
    await page.evaluate((id) => {
      const viewer = (window as typeof window & { viewer3dTest: Viewer }).viewer3dTest
      viewer.setStorey(null)
      viewer.highlight([id], { cameraTargetItemId: id })
    }, detail.item_id)
    expect(await region.locator('canvas').evaluate((canvas: LinkedViewerCanvas, id) => canvas.__viewer3d!.pick(id), detail.item_id)).toBe(true)
    const card = region.getByLabel('Item details', { exact: true })
    await expect(card.getByLabel('Wall measurements')).toBeVisible()
    await expect(card).toContainText(detail.wall_details.status)
    await expect(card).toContainText(detail.wall_details.height_source)
    await expect(card).toContainText('Openings deducted')
    await expect(card).toContainText('Net')
    expect(detail.wall_details.length_m).toBeGreaterThan(0)
    expect(detail.wall_details.faces[0].net_m2).not.toBeNull()
    await expect(card).not.toContainText('No additional properties')
    expect(detailRequests).toBe(1)
    const ask = card.getByRole('link', { name: 'Ask about this wall' })
    await expect(ask).toHaveAttribute('href', new RegExp(`doc=${docId}`))
    await expect.poll(async () => card.evaluate((node) => node.getBoundingClientRect().height)).toBeGreaterThan(100)
    await region.screenshot({ path: path.join(root, 'results/final/WALLPANEL', `${docId}.panel.png`) })
    await card.getByRole('button', { name: 'Close item details' }).click()
    await region.locator('canvas').evaluate((canvas: LinkedViewerCanvas, id) => canvas.__viewer3d!.pick(id), detail.item_id)
    await expect(card.getByLabel('Wall measurements')).toBeVisible()
    expect(detailRequests).toBe(1)
    await card.getByRole('link', { name: 'Ask about this wall' }).click()
    await expect(page.getByLabel('Ask about your drawings')).toHaveValue(/Tell me about wall/)
    await expect(page.getByLabel('Selected documents')).toContainText(document.title)
  })
}

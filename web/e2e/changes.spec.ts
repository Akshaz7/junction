import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import type { ChangeEntry, Comparison } from '../src/lib/types'

const api = 'http://localhost:8000'
test.setTimeout(60_000)

test('real synthetic revision shows numbered changes and a draggable wipe, then opens a new document', async ({ page, request }) => {
  const response = await request.get(`${api}/api/changes`)
  expect(response.ok()).toBe(true)
  const { changes: feed } = await response.json() as { changes: ChangeEntry[] }
  const revision = feed.find((entry) => entry.type === 'new_version' && entry.summary.generated_for_demo)
  expect(revision, 'Seed a synthetic revision on the real API before this done test').toBeTruthy()
  const detail = await request.get(`${api}/api/changes/${revision!.id}`)
  expect(detail.ok()).toBe(true)
  const comparison = await detail.json() as Comparison
  expect(comparison.generated_for_demo).toBe(true)
  expect(comparison.changes.length).toBeGreaterThan(0)

  await page.goto('/#/changes')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await page.locator(`.change-row[data-change-id="${revision!.id}"]`).click()
  await expect(page.locator('.comparison-box')).toBeVisible()
  await expect(page.locator('.comparison-header')).toContainText('generated for demo')
  await expect(page.getByRole('img', { name: 'Previous revision', exact: true })).toHaveAttribute('src', comparison.v1.page_image)
  await expect(page.getByRole('img', { name: 'Latest revision', exact: true })).toHaveAttribute('src', comparison.v2.page_image)
  await expect.poll(() => page.locator('.comparison-sheet > img').evaluateAll((nodes) => nodes.every((node) => (node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth > 0))).toBe(true)
  const readings = page.getByRole('complementary', { name: 'Change readings', exact: true })
  await expect(readings.locator('article')).toHaveCount(comparison.changes.length)
  for (const change of comparison.changes) {
    const row = readings.locator(`article[data-change-id="${change.change_id}"]`)
    await expect(row.locator('.reading-number')).toHaveText(String(change.n))
    await expect(row.locator('p')).toHaveText(change.sentence)
  }
  const boxed = comparison.changes.filter((change) => (change.v2 || change.v1)?.bbox_px)
  await expect(page.locator('.change-region')).toHaveCount(boxed.length)
  await page.getByLabel('Change boxes', { exact: true }).uncheck()
  await expect(page.locator('.change-region')).toHaveCount(0)
  await page.getByLabel('Change boxes', { exact: true }).check()
  await expect(page.locator('.change-region')).toHaveCount(boxed.length)

  await page.getByRole('button', { name: 'Wipe', exact: true }).click()
  const slider = page.getByRole('slider', { name: 'Wipe position', exact: true })
  await expect(slider).toHaveValue('50')
  const bounds = (await slider.boundingBox())!
  await page.mouse.move(bounds.x + bounds.width * .5, bounds.y + bounds.height * .5)
  await page.mouse.down()
  await page.mouse.move(bounds.x + bounds.width * .75, bounds.y + bounds.height * .5, { steps: 5 })
  await expect(slider).toHaveValue('75')
  const seam = await page.locator('.wipe-seam').boundingBox()
  expect(Math.abs(seam!.x - (bounds.x + bounds.width * .75))).toBeLessThan(3)
  await page.mouse.up()
  await expect(page.getByRole('img', { name: 'Latest revision', exact: true })).toHaveCSS('clip-path', 'inset(0px 0px 0px 75%)')
  await slider.press('ArrowLeft')
  await expect(slider).toHaveValue('74')
  await page.getByRole('button', { name: 'Overlay', exact: true }).click()
  await expect(slider).toHaveCount(0)
  await expect(page.getByRole('img', { name: 'Latest revision', exact: true })).toHaveCSS('opacity', '0.5')
  await page.getByRole('button', { name: 'Plain', exact: true }).click()
  await expect(page.getByRole('img', { name: 'Latest revision', exact: true })).toHaveCSS('opacity', '1')

  // A real upload also verifies the second feed group, including switching away
  // from a loaded revision without displaying its stale images/readings.
  const upload = await request.post(`${api}/api/upload`, { multipart: { file: {
    name: `changes-${Date.now()}-generated-for-demo.png`, mimeType: 'image/png',
    buffer: readFileSync(new URL('./assets/upload-fixture.png', import.meta.url)),
  } } })
  expect(upload.ok()).toBe(true)
  const receipt = await upload.json() as { doc_id: string }
  await page.getByRole('button', { name: 'Refresh changes', exact: true }).click()
  await page.locator(`.change-row[data-change-id="doc:${receipt.doc_id}"]`).click()
  await expect(page.locator('.comparison-box')).toHaveCount(0)
  await expect(page.getByText('This is a new document; no previous revision is available.', { exact: true })).toBeVisible()
  await page.locator(`.change-row[data-change-id="${revision!.id}"]`).click()
  await page.getByRole('button', { name: 'Wipe', exact: true }).click()
  await expect(page.getByRole('slider', { name: 'Wipe position', exact: true })).toHaveValue('50')
})

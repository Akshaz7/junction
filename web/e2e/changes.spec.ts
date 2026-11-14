import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'
import type { ChangeEntry, ChangeFeedEntry, Comparison, Document } from '../src/lib/types'

const api = 'http://localhost:8000'
test.setTimeout(60_000)

test('real revision series shows numbered changes and a draggable wipe, then opens a new document', async ({ page, request }) => {
  const response = await request.get(`${api}/api/changes`)
  expect(response.ok()).toBe(true)
  const { changes: feed } = await response.json() as { changes: ChangeFeedEntry[] }
  expect(feed.length).toBeGreaterThan(0)
  const docsResponse = await request.get(`${api}/api/docs`)
  expect(docsResponse.ok()).toBe(true)
  const { sources } = await docsResponse.json() as { sources: { docs: Document[] }[] }
  const docIds = new Set(sources.flatMap((source) => source.docs.map((doc) => doc.doc_id)))
  // Check the first entries as well as every revision: synthetic pairs must not
  // return ahead of the real feed, even if a later real comparison still works.
  for (const entry of feed) {
    expect(entry).not.toHaveProperty('generated_for_demo')
    expect(entry.summary ?? {}).not.toHaveProperty('generated_for_demo')
    if (entry.type === 'rule_change') continue
    expect(entry.doc_b).toBeTruthy()
    for (const docId of [entry.doc_a, entry.doc_b, entry.summary.doc_id].filter((id) => id != null)) {
      expect(docIds.has(docId), `${entry.id}: ${docId} must be a listed document`).toBe(true)
      expect(docId).not.toContain('@')
      expect(docId).not.toMatch(/^swiss_dwellings__.*-v\d+$/)
    }
  }
  const revisions = feed.filter((entry): entry is ChangeEntry => entry.type === 'new_version')
    .filter((entry) => entry.summary.source === 'pdf-diff' && (entry.summary.n_changes ?? 0) > 0)
  expect(revisions.length, 'The real API must serve revision series').toBeGreaterThan(0)
  const revision = revisions.reduce((best, entry) => (entry.summary.n_changes! < best.summary.n_changes! ? entry : best))
  const detail = await request.get(`${api}/api/changes/${revision!.id}`)
  expect(detail.ok()).toBe(true)
  const comparison = await detail.json() as Comparison
  expect(comparison).not.toHaveProperty('generated_for_demo')
  expect(comparison.changes.length).toBeGreaterThan(0)

  await page.goto('/#/changes')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await page.locator(`.change-row[data-change-id="${revision!.id}"]`).click()
  await expect(page.locator('.comparison-box')).toBeVisible()
  await expect(page.locator('.comparison-header')).not.toContainText('pdf-diff')
  await expect(page.getByRole('img', { name: 'Previous revision', exact: true })).toHaveAttribute('src', comparison.v1.page_image)
  await expect(page.getByRole('img', { name: 'Latest revision', exact: true })).toHaveAttribute('src', comparison.v2.page_image)
  await expect.poll(() => page.locator('.sc-sheet > img').evaluateAll((nodes) => nodes.every((node) => (node as HTMLImageElement).complete && (node as HTMLImageElement).naturalWidth > 0))).toBe(true)
  const readings = page.getByRole('complementary', { name: 'Change readings', exact: true })
  await expect(readings.locator('article')).toHaveCount(comparison.changes.length)
  for (const change of comparison.changes) {
    const row = readings.locator(`article[data-change-id="${change.change_id}"]`)
    await expect(row.locator('.reading-number')).toHaveText(String(change.n))
    await expect(row.locator('p')).not.toBeEmpty()
  }
  const boxed = comparison.changes.filter((change) => (change.v2 || change.v1)?.bbox_px)
  await expect(page.locator('.change-region')).toHaveCount(boxed.length)
  await page.getByLabel('Change boxes', { exact: true }).uncheck()
  await expect(page.locator('.change-region')).toHaveCount(0)
  await page.getByLabel('Change boxes', { exact: true }).check()
  await expect(page.locator('.change-region')).toHaveCount(boxed.length)

  await page.getByRole('button', { name: 'Wipe', exact: true }).click()
  const slider = page.getByRole('slider', { name: 'Wipe position', exact: true })
  await expect(slider).toHaveAttribute('aria-valuenow', '50', { timeout: 5000 })
  const canvas = (await page.locator('.sc-canvas').boundingBox())!
  const grip = (await slider.boundingBox())!
  await page.mouse.move(grip.x + grip.width / 2, grip.y + grip.height / 2)
  await page.mouse.down()
  await page.mouse.move(canvas.x + canvas.width * .75, grip.y + grip.height / 2, { steps: 5 })
  await expect(slider).toHaveAttribute('aria-valuenow', /^7[45](\.\d)?$/)
  await page.mouse.up()
  await expect(page.locator('.sc-curr')).toHaveCSS('clip-path', /inset\(0px 0px 0px 7[45]/)
  await slider.focus()
  await slider.press('ArrowLeft')
  await expect(slider).toHaveAttribute('aria-valuenow', /^7[34](\.\d)?$/)
  // A card zooms the canvas to its change, Escape returns to the fitted sheet.
  const first = readings.locator('article.sc-card').first()
  await first.click()
  await expect(page.locator('.sc-box[data-active]')).toHaveCount(1)
  await page.keyboard.press('Escape')
  await expect(page.locator('.sc-box[data-active]')).toHaveCount(0)
  await page.getByRole('button', { name: 'Overlay', exact: true }).click()
  await expect(slider).toHaveCount(0)
  await expect(page.locator('.sc-opacity input')).toHaveValue('50')
  await page.getByRole('button', { name: 'Plain', exact: true }).click()
  await expect(page.getByRole('img', { name: 'Latest revision', exact: true })).toBeVisible()

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
  await expect(page.getByRole('slider', { name: 'Wipe position', exact: true })).toHaveAttribute('aria-valuenow', '50', { timeout: 5000 })
})

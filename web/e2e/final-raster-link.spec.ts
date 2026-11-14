import { test, expect, production, chooseDocument, chatFor, ask, viewerState } from './final-helpers'

test.use({ viewport: { width: 1440, height: 1000 } })
test.setTimeout(180_000)

test('[ENGINE] Raster answer boxes keep the same item identities when visualised in 3D', async ({ page, request }) => {
  test.skip(production, 'Production is read-only; no new raster question')
  const doc = await chooseDocument(request, 'raster')
  await chatFor(page, doc)
  const answer = await ask(page, 'How many doors are there?')
  const card = page.getByTestId('answer-card').last()
  expect(answer.evidence.boxes.length, 'Raster answer provides numbered drawing boxes').toBeGreaterThan(0)
  await card.locator('.sources-summary').click()
  await card.locator('.sources-detail').getByRole('button', { name: `Open citation ${answer.citations[0].n}`, exact: true }).click()
  const drawing = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await expect(drawing.locator('svg.drawing-evidence g[data-item-id]').first()).toBeVisible()
  await page.screenshot({ path: test.info().outputPath('raster-2d-evidence.png') })
  await card.getByRole('button', { name: 'Visualise it', exact: true }).click()
  const viewer = page.getByRole('region', { name: '3D viewer', exact: true }).filter({ visible: true })
  await expect(viewer).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
  const scene = await request.get(`/api/docs/${encodeURIComponent(doc.doc_id)}/scene`)
  expect(scene.ok()).toBe(true)
  const manifest = await scene.json()
  const expected = answer.evidence.scene.highlight_item_ids
  const unresolved = expected.filter((id) => !manifest.items[id])
  await test.info().attach('raster-scene-link.json', { body: JSON.stringify({
    doc_id: doc.doc_id, answer_id: answer.answer_id, expected, unresolved,
    actual: (await viewerState(page)).highlights,
  }, null, 2), contentType: 'application/json' })
  await page.screenshot({ path: test.info().outputPath('raster-3d-evidence.png') })
  expect.soft(unresolved, 'Every answer highlight resolves to a real scene item').toEqual([])
  await expect.poll(async () => (await viewerState(page)).highlights.sort(), { message: 'The same numbered items glow in 3D' }).toEqual([...expected].sort())
})

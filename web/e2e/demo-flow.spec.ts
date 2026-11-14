import { expect, test } from '@playwright/test'
import type { Document } from '../src/lib/types'
import { ac20, api, ask, countQuestion, openDrawing, rasterPick, selectFromData, shot, viewerState, visualise } from './demo-helpers'

// Live stack only: start the API on :8000 and seed docs/DEMO.md's picks.
// Every ask has its own 60 s deadline; the desktop scenario makes five asks.
test.use({
  viewport: { width: 1280, height: 800 },
  actionTimeout: 15_000,
  launchOptions: {
    executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  },
})
test.setTimeout(420_000)

test('desktop: live raster proof carries into 3D, then AC20 door evidence and scene edits', async ({ page }) => {
  const raster = await rasterPick(page)
  await page.goto('/?viewer3dTest=1#/overview')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await selectFromData(page, raster.doc, false)
  await shot(page, 'desktop-01-raster-selected')

  const counted = await ask(page, countQuestion, raster.doc.doc_id, true)
  expect(counted.answer.answer.value, raster.candidate).toBe(raster.gold)
  await expect(counted.card.locator('.answer-text strong')).toContainText(new RegExp(`\\b${raster.gold}\\b`))
  expect(counted.answer.citations.length).toBeGreaterThan(0)
  await expect(counted.card.locator('.answer-text .citation-chip').first()).toBeVisible()
  await shot(page, 'desktop-02-raster-answer')

  const drawing = await openDrawing(page, counted.card, counted.answer, false)
  expect(counted.answer.evidence.boxes).toHaveLength(raster.gold)
  expect([...new Set(counted.answer.evidence.boxes.map((box) => box.item_id))].sort())
    .toEqual([...counted.answer.evidence.scene.highlight_item_ids].sort())
  await shot(page, 'desktop-03-numbered-drawing')
  const rasterPanel = await visualise(page, drawing, counted.answer)
  await shot(page, 'desktop-04-raster-3d')
  await rasterPanel.getByRole('button', { name: 'Close 3D view', exact: true }).click()
  await drawing.getByRole('button', { name: 'Close drawing viewer', exact: true }).click()

  // Start a fresh UI chat so the raster count's selected document cannot leak into C13.
  const metadata = await page.request.get(`${api}/api/docs/${ac20}`)
  expect(metadata.ok()).toBe(true)
  const building = await metadata.json() as Document
  await page.goto('/?viewer3dTest=1#/overview')
  await page.reload()
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await selectFromData(page, building, false)
  await shot(page, 'desktop-05-ac20-selected')
  const narrowest = await ask(page, 'What is the narrowest door width used here?', ac20)
  await expect(narrowest.card.locator('.answer-text')).toContainText(/\b1(?:\.0+)?\s*m\b/)
  expect(narrowest.answer.citations).toHaveLength(1)
  expect(narrowest.answer.citations[0].item_ids).toHaveLength(1)
  expect(narrowest.answer.evidence.scene.highlight_item_ids).toEqual(narrowest.answer.citations[0].item_ids)
  await shot(page, 'desktop-06-narrowest-door-answer')
  await narrowest.card.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true }).click()
  const buildingDrawing = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  const buildingPanel = await visualise(page, buildingDrawing, narrowest.answer)
  await expect(buildingPanel).toHaveClass(/viewer3d-linked-panel/)
  await shot(page, 'desktop-07-narrowest-door-3d')

  const sceneResponse = await page.request.get(`${api}/api/docs/${ac20}/scene`)
  expect(sceneResponse.ok()).toBe(true)
  const scene = await sceneResponse.json() as { items: Record<string, { kind: string; tag?: string }> }
  const doorIds = Object.entries(scene.items).filter(([, item]) => item.kind === 'door').map(([id]) => id).sort()
  expect(doorIds, 'C23 gold from docs/DEMO.md').toHaveLength(77)
  const doors = await ask(page, 'show only the doors', ac20)
  expect(doors.answer.evidence.scene.commands).toContainEqual(expect.objectContaining({ op: 'isolate', item_ids: expect.arrayContaining(doorIds) }))
  await buildingPanel.getByLabel('Storey', { exact: true }).selectOption('')
  await expect.poll(async () => {
    const state = await viewerState(buildingPanel)
    return {
      isolated: state.commands.isolated?.slice().sort(),
      highlighted: state.highlight.highlighted.slice().sort(),
      visibleDoors: doorIds.filter((id) => !state.commands.hidden.includes(id) && state.commands.isolated?.includes(id)).length,
    }
  }, { timeout: 15_000 }).toEqual({ isolated: doorIds, highlighted: doorIds, visibleDoors: 77 })
  await shot(page, 'desktop-08-only-doors')

  // Resolve W3 from a fresh API manifest for this edit, never a saved fixture.
  const taggedSceneResponse = await page.request.get(`${api}/api/docs/${ac20}/scene`, {
    headers: { 'Cache-Control': 'no-cache' },
  })
  expect(taggedSceneResponse.ok()).toBe(true)
  const taggedScene = await taggedSceneResponse.json() as typeof scene
  const w3Items = Object.entries(taggedScene.items).filter(([, item]) => item.tag === 'W3')
  expect(w3Items, 'C20 must resolve exactly one real manifest tag W3').toHaveLength(1)
  const w3 = w3Items[0][0]

  const removed = await ask(page, 'remove W3', ac20)
  expect(removed.answer.evidence.scene.commands).toContainEqual(expect.objectContaining({ op: 'hide', item_ids: [w3] }))
  await expect.poll(async () => (await viewerState(buildingPanel)).commands.hidden, { timeout: 15_000 }).toContain(w3)
  await shot(page, 'desktop-09-w3-hidden')

  const reset = await ask(page, 'reset', ac20)
  expect(reset.answer.evidence.scene.commands).toContainEqual(expect.objectContaining({ op: 'reset' }))
  await expect.poll(async () => (await viewerState(buildingPanel)).commands, { timeout: 15_000 })
    .toEqual({ hidden: [], highlighted: {}, isolated: null })
  await expect.poll(async () => (await viewerState(buildingPanel)).highlight.highlighted).toEqual([])
  await shot(page, 'desktop-10-reset')
})

test('phone: live count opens a full-screen numbered drawing sheet with bottom tabs visible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const raster = await rasterPick(page)
  await page.goto('/?viewer3dTest=1#/overview')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  const tabs = page.getByRole('navigation', { name: 'Mobile navigation', exact: true })
  for (const label of ['Overview', 'Chat', 'Changes', 'Data']) {
    await expect(tabs.getByRole('link', { name: label, exact: true })).toBeInViewport()
  }
  await selectFromData(page, raster.doc, true)
  await expect(tabs.getByRole('link', { name: 'Chat', exact: true })).toHaveAttribute('aria-current', 'page')
  await shot(page, 'phone-01-raster-selected')
  const counted = await ask(page, countQuestion, raster.doc.doc_id, true)
  expect(counted.answer.answer.value, raster.candidate).toBe(raster.gold)
  await expect(counted.card.locator('.answer-text strong')).toContainText(new RegExp(`\\b${raster.gold}\\b`))
  await expect(counted.card.locator('.answer-text .citation-chip').first()).toBeVisible()
  await shot(page, 'phone-02-raster-answer')

  const drawing = await openDrawing(page, counted.card, counted.answer, true)
  expect(counted.answer.evidence.boxes).toHaveLength(raster.gold)
  await expect.poll(async () => {
    const bounds = await drawing.boundingBox()
    return !!bounds && bounds.x <= 1 && bounds.y <= 1 && bounds.width >= 389 && bounds.height >= 843
  }).toBe(true)
  await shot(page, 'phone-03-fullscreen-evidence')
  await drawing.getByRole('button', { name: 'Close drawing viewer', exact: true }).click()
  for (const label of ['Overview', 'Chat', 'Changes', 'Data']) {
    await expect(tabs.getByRole('link', { name: label, exact: true })).toBeVisible()
    await expect(tabs.getByRole('link', { name: label, exact: true })).toBeInViewport()
  }
  await shot(page, 'phone-04-tabs-after-evidence')
})

// Keep real tab hit testing independent of the live answer/evidence assertions.
// No forced click or hash navigation: a preview covering Chat must fail here.
test('phone: Data page preview leaves the Chat bottom tab tappable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const raster = await rasterPick(page)
  await page.goto('/?viewer3dTest=1#/overview')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await selectFromData(page, raster.doc, true)
  const tabs = page.getByRole('navigation', { name: 'Mobile navigation', exact: true })
  await tabs.getByRole('link', { name: 'Data', exact: true }).click()
  await expect(page).toHaveURL(/#\/data$/)
  const preview = page.getByRole('complementary', { name: 'Document details' })
    .getByRole('img', { name: `First page of ${raster.doc.title}`, exact: true })
  await expect(preview).toBeVisible()
  await expect.poll(() => preview.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true)
  await shot(page, 'phone-tabs-01-data-preview')
  try {
    await tabs.getByRole('link', { name: 'Chat', exact: true }).click()
    await expect(page).toHaveURL(/#\/chat$/)
    await expect(tabs.getByRole('link', { name: 'Chat', exact: true })).toHaveAttribute('aria-current', 'page')
    await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeVisible()
    await expect(page.getByLabel('Selected documents')).toContainText(raster.doc.title)
  } finally {
    await shot(page, 'phone-tabs-02-after-chat-tap')
  }
})

import { expect, test } from '@playwright/test'

// FIX-2: with a drawing open, the next answer about the same document updates the pane in place.
const docId = 'cubicasa5k__colorful-11397'

test('next answer swaps boxes in place: same image element, zoom kept, under 1 s', async ({ page, request }) => {
  const created = await request.post('http://localhost:8000/api/chats', { data: { doc_ids: [docId], title: 'FIX-2 in place' } })
  expect(created.ok()).toBe(true)
  const { id } = await created.json() as { id: string }
  const first = await request.post(`http://localhost:8000/api/chats/${id}/messages`, { data: { doc_ids: [docId], content: 'How many windows are there?' }, timeout: 45_000 })
  expect(first.ok()).toBe(true)
  await first.text()

  await page.goto(`/#/chat?chat=${encodeURIComponent(id)}`)
  await page.getByRole('button', { name: 'Open citation 1', exact: true }).last().click()
  const viewer = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await expect(viewer).toBeVisible()
  const image = viewer.getByRole('img', { name: /Drawing:/ })
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true)
  const boxIds = () => viewer.locator('g.evidence-region:not(.is-leaving)').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('data-item-id')))
  await expect.poll(async () => (await boxIds()).length).toBeGreaterThan(0)
  const windows = await boxIds()
  expect(windows.every((item) => /window/.test(item ?? ''))).toBe(true)

  // Zoom in so a reset would be visible, then tag the live image node.
  await viewer.getByRole('button', { name: /zoom in/i }).first().click()
  const plane = viewer.locator('.drawing-plane')
  await expect.poll(async () => { const a = await plane.evaluate((node) => getComputedStyle(node).transform); await page.waitForTimeout(150); return a === await plane.evaluate((node) => getComputedStyle(node).transform) }).toBe(true)
  const transform = await plane.evaluate((node) => getComputedStyle(node).transform)
  await image.evaluate((node) => { (node as HTMLImageElement & { __mark?: string }).__mark = 'same-node' })
  const imageRequests: string[] = []
  page.on('request', (req) => { if (/\/pages\/\d+\/image/.test(req.url())) imageRequests.push(req.url()) })

  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('How many doors are there?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  await expect.poll(async () => { const now = await boxIds(); return now.length > 0 && now.every((item) => /door/.test(item ?? '')) }, { timeout: 30_000 }).toBe(true)

  expect(await image.evaluate((node) => (node as HTMLImageElement & { __mark?: string }).__mark)).toBe('same-node')
  expect(imageRequests).toEqual([])
  expect(await plane.evaluate((node) => getComputedStyle(node).transform)).toBe(transform)
  // Old boxes are gone once the fade (0.4 s) has finished.
  await expect(viewer.locator('g.evidence-region.is-leaving')).toHaveCount(0, { timeout: 1000 })
})

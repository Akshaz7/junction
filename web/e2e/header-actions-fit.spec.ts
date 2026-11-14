import { expect, test } from '@playwright/test'

const api = 'http://localhost:8000'
const docId = 'cubicasa5k__colorful-11397'
test.setTimeout(90_000)

test('chat header actions never overlap the viewer pane at any chat width', async ({ page, request }) => {
  const created = await request.post(`${api}/api/chats`, { data: { doc_ids: [docId], title: `W-54 ${Date.now()}` } })
  const { id } = await created.json() as { id: string }
  const sent = await request.post(`${api}/api/chats/${id}/messages`, { data: { content: 'How many windows are there?', doc_ids: [docId] } })
  expect(sent.ok()).toBe(true)
  await sent.text()
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/#/chat/${id}`)
  await page.locator('.answer-text').getByRole('button', { name: /Open citation/ }).first().click()
  const viewer = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await expect(viewer).toBeVisible()
  const handle = page.getByRole('separator', { name: 'Resize chat and drawing' })
  for (const width of [1100, 1333, 1583, 2000]) {
    await page.setViewportSize({ width, height: 900 })
    await page.waitForTimeout(700) // split transition
    const chat = await page.locator('.chat-workspace.has-viewer > :first-child').boundingBox()
    const pane = (await viewer.boundingBox())!
    for (const button of await page.locator('.chat-header-actions .button').all()) {
      const box = (await button.boundingBox())!
      expect(box.x + box.width, `actions at ${width}px (chat ${Math.round(chat?.width ?? 0)}px)`).toBeLessThanOrEqual(pane.x + 1)
    }
  }
  // Narrowest allowed chat split (35%) at a wide window.
  await page.setViewportSize({ width: 2000, height: 900 })
  await handle.focus()
  for (let i = 0; i < 8; i++) await page.keyboard.press('ArrowLeft')
  await page.waitForTimeout(700)
  const pane = (await viewer.boundingBox())!
  for (const button of await page.locator('.chat-header-actions .button').all()) {
    const box = (await button.boundingBox())!
    expect(box.x + box.width, 'actions at 35% split').toBeLessThanOrEqual(pane.x + 1)
  }
})

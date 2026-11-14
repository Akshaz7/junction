import { devices, expect, test } from '@playwright/test'

const { defaultBrowserType: _ignored, ...phone } = devices['iPhone 15 Pro Max']
test.use({ ...phone, viewport: { width: 390, height: 844 } })
test.setTimeout(90_000)
const api = 'http://localhost:8000'
const docId = 'ifc_bench__ac20-arc'

for (const question of ['remove the front door', 'How many doors and windows are there?']) {
  test(`phone chat never scrolls sideways: ${question}`, async ({ page, request }) => {
    const { id } = await (await request.post(`${api}/api/chats`, { data: { doc_ids: [docId], title: 'W-hscroll' } })).json() as { id: string }
    const sent = await request.post(`${api}/api/chats/${id}/messages`, { data: { content: question, doc_ids: [docId] } })
    expect(sent.ok()).toBe(true)
    await sent.text()
    await page.goto(`/#/chat/${id}`)
    await page.locator('.answer-text').first().waitFor({ timeout: 30_000 })
    await page.waitForTimeout(1500)
    const wide = await page.evaluate(() => {
      const view = document.documentElement.clientWidth
      return [...document.querySelectorAll('.exchange *')].filter((el) => el.getBoundingClientRect().right > view + 1 && getComputedStyle(el).visibility !== 'hidden')
        .slice(0, 12).map((el) => `${el.tagName}.${(el.getAttribute('class') ?? '').slice(0, 40)} right=${Math.round(el.getBoundingClientRect().right)}`)
    })
    expect(wide, 'elements past the right edge').toEqual([])
    const sizes = await page.evaluate(() => ({ scroll: document.scrollingElement!.scrollWidth, client: document.scrollingElement!.clientWidth }))
    expect(sizes.scroll).toBe(sizes.client)
    // header actions never sit on top of the chat content
    const actions = await page.locator('.chat-header-actions').boundingBox()
    const first = await page.locator('.exchange').first().boundingBox()
    if (actions && first) expect(actions.y + actions.height).toBeLessThanOrEqual(first.y + 1)
  })
}

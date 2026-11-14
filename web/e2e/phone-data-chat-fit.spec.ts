import { devices, expect, test } from '@playwright/test'

const { defaultBrowserType: _ignored, ...phone } = devices['iPhone 15 Pro Max']
test.use({ ...phone, viewport: { width: 390, height: 844 } })
test.setTimeout(90_000)
const api = 'http://localhost:8000'
const docId = 'ifc_bench__ac20-arc'
const shots = process.env.SHOTS_DIR ?? 'test-results'

async function overflow(page: import('@playwright/test').Page, scope: string) {
  return page.evaluate((sel) => {
    const view = document.documentElement.clientWidth
    const bad = [...document.querySelectorAll(`${sel} *`)].filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && (r.right > view + 1 || r.left < -1) && getComputedStyle(el).visibility !== 'hidden' })
      .slice(0, 12).map((el) => `${el.tagName}.${(el.getAttribute('class') ?? '').slice(0, 40)} ${Math.round(el.getBoundingClientRect().left)}..${Math.round(el.getBoundingClientRect().right)}`)
    return { bad, scroll: document.scrollingElement!.scrollWidth, client: document.scrollingElement!.clientWidth }
  }, scope)
}

test('phone Data page fits 390 px', async ({ page }) => {
  await page.goto('/#/data')
  await page.locator('[data-doc-id]').first().waitFor({ timeout: 30_000 })
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${shots}/phone-data-list.png`, fullPage: false })
  const r = await overflow(page, 'main, .workspace')
  expect(r.bad).toEqual([])
  expect(r.scroll).toBe(r.client)
  await page.locator('[data-doc-id] .data-open-file').first().click()
  await page.waitForTimeout(800)
  await page.screenshot({ path: `${shots}/phone-data-detail.png` })
  const d = await overflow(page, '.data-detail')
  expect(d.bad).toEqual([])
  expect(d.scroll).toBe(d.client)
})

test('phone chat answer fits 390 px', async ({ page, request }) => {
  const { id } = await (await request.post(`${api}/api/chats`, { data: { doc_ids: [docId], title: 'W-fit' } })).json() as { id: string }
  const sent = await request.post(`${api}/api/chats/${id}/messages`, { data: { content: 'How many doors and windows are there?', doc_ids: [docId] } })
  await sent.text()
  await page.goto(`/#/chat/${id}`)
  await page.locator('.answer-text').first().waitFor({ timeout: 30_000 })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: `${shots}/phone-chat-answer.png` })
  const r = await overflow(page, '.workspace')
  expect(r.bad).toEqual([])
  expect(r.scroll).toBe(r.client)
})

import { expect, test, type Page } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
const api = process.env.MARKUP_API_ORIGIN || 'http://127.0.0.1:8387'
const output = '../results/final/MARKUP'

/** Pins, listing and the sheet go to the isolated test API; saving one marked item uses the real one-item API unless MARKUP_MOCK_SAVE=1 mocks it in memory. */
async function setup(page: Page) {
  await mkdir(output, { recursive: true })
  await page.request.post(`${api}/test-reset`)
  const marks: Record<string, unknown>[] = []
  await page.route('**/api/**', async (route) => {
    const request = route.request(), url = new URL(request.url())
    const one = url.pathname.match(/\/markup\/symbols(?:\/([^/]+))?$/)
    if (one && process.env.MARKUP_MOCK_SAVE === '1') {
      const id = one[1], body = request.postDataJSON?.() ?? {}
      if (request.method() === 'POST') {
        const mark = { id: `m${marks.length + 1}`, doc_id: 'sheet-under-test', name: body.name, note: '', page: body.page, template_bbox: body.box, canonical_kind: body.canonical_kind ?? null, matches: [{ id: '1', bbox: body.box, score: 1, status: 'confirmed', room: null }], summary: { found: 1, confirmed: 1, pending: 0, rejected: 0, rooms: {} } }
        marks.push(mark); return route.fulfill({ status: 201, json: mark })
      }
      const at = marks.findIndex((m) => m.id === id)
      if (request.method() === 'PATCH') { Object.assign(marks[at], { name: body.name, canonical_kind: body.canonical_kind }); return route.fulfill({ json: marks[at] }) }
      if (request.method() === 'DELETE') { marks.splice(at, 1); return route.fulfill({ status: 204 }) }
    }
    url.host = new URL(api).host
    const response = await route.fetch({ url: url.href })
    if (process.env.MARKUP_MOCK_SAVE === '1' && url.pathname.endsWith('/markup') && request.method() === 'GET') return route.fulfill({ response, json: { ...(await response.json()), symbols: marks } })
    await route.fulfill({ response })
  })
  await page.routeWebSocket('**/ws', () => {})
}
async function drag(page: Page, fx: number, fy: number, tx: number, ty: number) {
  const b = (await page.locator('.drawing-plane > img').boundingBox())!
  await page.mouse.move(b.x + b.width * fx, b.y + b.height * fy)
  await page.mouse.down(); await page.mouse.move(b.x + b.width * tx, b.y + b.height * ty, { steps: 5 }); await page.mouse.up()
}

test('mark single items on a dense sheet, edit one, delete one, keep a pin', async ({ page }) => {
  await setup(page)
  await page.goto('/e2e/markup-viewer.html')
  await expect(page.locator('.drawing-plane > img')).toBeVisible()
  await page.getByRole('button', { name: 'Highlight marker', exact: true }).click()
  await expect.poll(() => page.locator('.drawing-stage').evaluate((n) => n.clientHeight)).toBeGreaterThan(100)
  await page.getByRole('button', { name: 'Fit drawing', exact: true }).click()
  await drag(page, 0.89, 0.40, 0.896, 0.405)
  const bubble = page.getByTestId('tell-stoa')
  await expect(bubble).toBeVisible()
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${output}/tell-stoa-bubble.png` })
  const at = (await bubble.boundingBox())!
  await page.screenshot({ path: `${output}/tell-stoa-bubble-close.png`, clip: { x: Math.max(0, at.x - 260), y: Math.max(0, at.y - 160), width: 620, height: 330 } })
  await bubble.getByRole('textbox').fill('door')
  await expect(bubble.locator('.tell-stoa-chip, .tell-stoa-status')).toHaveCount(0)
  await page.keyboard.press('Enter')
  await expect(bubble).toHaveCount(0)
  const tags = page.locator('.taught-mark')
  await expect(tags).toHaveCount(1)
  await expect(tags.first().locator('text')).toHaveText('Door')
  // A second, ad hoc item: free text, send with the button. The highlighter stays on.
  await drag(page, 0.5, 0.5, 0.506, 0.506)
  await page.getByTestId('tell-stoa').getByRole('textbox').fill('Air terminal')
  await page.getByRole('button', { name: 'Save mark' }).click()
  await expect(tags).toHaveCount(2)
  await page.screenshot({ path: `${output}/tell-stoa-marked.png` })
  // Saved marks show on a plain page load, without opening the Marks panel.
  await page.reload()
  await expect(page.locator('.drawing-plane > img')).toBeVisible()
  await expect(tags).toHaveCount(2)
  await page.getByRole('button', { name: 'Fit drawing', exact: true }).click().catch(() => {})
  await page.screenshot({ path: `${output}/tell-stoa-marks-on-load.png` })
  // Click a saved mark: rename it, then delete the other.
  await tags.first().click()
  await expect(bubble).toBeVisible()
  await bubble.getByRole('textbox').fill('Window'); await page.keyboard.press('Enter')
  await expect(tags.first().locator('text')).toHaveText('Window')
  await tags.nth(1).click()
  await page.waitForTimeout(300)
  await page.screenshot({ path: `${output}/tell-stoa-edit.png` })
  await bubble.getByRole('button', { name: 'Delete mark' }).click()
  await expect(tags).toHaveCount(1)
  await page.getByRole('button', { name: 'Place a note pin' }).click()
  const b = (await page.locator('.drawing-plane > img').boundingBox())!
  await page.mouse.click(b.x + b.width * .4, b.y + b.height * .65)
  await page.getByRole('textbox', { name: 'Pin note', exact: true }).fill('Check ceiling clearance before ordering.')
  await page.getByRole('button', { name: 'Save pin', exact: true }).click()
  await expect(page.locator('.markup-pin-list').last()).toContainText('Check ceiling clearance before ordering.')
  await page.getByRole('button', { name: 'Export report', exact: true }).click()
  const frame = page.frameLocator('iframe[title="Site report preview"]')
  await expect(frame.getByText('Check ceiling clearance before ordering.', { exact: true })).toBeVisible()
})

test('the Tell Stoa bubble fits a phone screen and Escape closes it', async ({ page }) => {
  await setup(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/e2e/markup-viewer.html')
  await expect(page.locator('.drawing-plane > img')).toBeVisible()
  await page.getByRole('button', { name: 'Highlight marker', exact: true }).click()
  await expect.poll(() => page.locator('.drawing-stage').evaluate((n) => n.clientHeight)).toBeGreaterThan(100)
  await drag(page, 0.2, 0.2, 0.23, 0.24)
  const bubble = page.getByTestId('tell-stoa')
  await expect(bubble).toBeVisible()
  await page.waitForTimeout(300)
  const at = (await bubble.boundingBox())!
  expect(at.x).toBeGreaterThanOrEqual(0); expect(at.x + at.width).toBeLessThanOrEqual(390)
  await page.screenshot({ path: `${output}/tell-stoa-bubble-phone.png` })
  await bubble.getByRole('textbox').press('Escape')
  await expect(bubble).toHaveCount(0)
})

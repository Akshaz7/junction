import { expect, test, type Locator, type Page } from '@playwright/test'
import { demoDocument, handleMockRequest, makeDemoAnswer } from '../src/mock/handler'

test.beforeEach(async ({ page }) => {
  // Generated demo fixtures keep keyboard checks independent of the shared API/DB.
  await page.routeWebSocket('**/ws', () => {})
  await page.route('**/api/**', (route) => route.fulfill({ json: route.request().url().endsWith('/docs')
    ? { sources: [{ source: 'demo', docs: [demoDocument] }] }
    : { chats: [], skills: [], automations: [] } }))
  await page.goto('/#/chat')
  await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeEnabled()
})

async function tabTo(page: Page, target: Locator) {
  for (let count = 0; count < 40; count++) {
    await page.keyboard.press('Tab')
    if (await target.evaluate((node) => node === document.activeElement)) return
  }
  throw new Error(`Tab did not reach ${await target.getAttribute('aria-label') || await target.getAttribute('id')}`)
}

test('chat Tab order reaches five controls with visible token-colored focus rings', async ({ page }) => {
  const controls = [
    page.getByRole('button', { name: 'New chat', exact: true }),
    page.getByRole('button', { name: 'History', exact: true }),
    page.getByRole('button', { name: 'Share', exact: true }),
    page.getByRole('button', { name: 'Pair a phone', exact: true }),
    page.getByRole('combobox', { name: 'Ask about your drawings' }),
  ]
  for (const control of controls) {
    await tabTo(page, control)
    await expect(control).toBeFocused()
    await expect(control).toBeInViewport()
    const ring = await control.evaluate((node) => {
      const style = getComputedStyle(node)
      const token = document.createElement('span')
      token.style.color = 'var(--ring)'
      document.body.appendChild(token)
      const tokenColor = getComputedStyle(token).color
      token.remove()
      return { visible: node.matches(':focus-visible'), width: parseFloat(style.outlineWidth), style: style.outlineStyle, color: style.outlineColor, tokenColor }
    })
    expect(ring.visible).toBe(true)
    expect(ring.width).toBeGreaterThanOrEqual(2)
    expect(ring.style).toBe('solid')
    expect(ring.color).toBe(ring.tokenColor)
  }
})

test('keyboard opens History and pairing, then Escape returns focus to each trigger', async ({ page }) => {
  for (const name of ['History', 'Pair a phone']) {
    const trigger = page.getByRole('button', { name, exact: true })
    await tabTo(page, trigger)
    await page.keyboard.press('Enter')
    const dialog = page.getByRole('dialog', { name: name === 'History' ? 'Chat history' : name, exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(trigger).toBeFocused()
  }
})

async function mockDrawing(page: Page) {
  await page.route('**/api/docs/**', async (route) => {
    const response = await handleMockRequest(new Request(route.request().url()))
    if (response) await route.fulfill({ status: response.status, headers: Object.fromEntries(response.headers), body: await response.text() })
    else await route.fulfill({ status: 404, json: { detail: 'No artifact in this demo fixture.' } })
  })
}

test('mobile Data traps focus and dismisses credit and search before closing its titled sheet', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockDrawing(page)
  await page.goto('/#/data')
  const trigger = page.getByRole('button', { name: `Open ${demoDocument.title}`, exact: true })
  await tabTo(page, trigger)
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: /^Garden room/ })
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  for (let count = 0; count < 20; count++) {
    await page.keyboard.press(count % 2 ? 'Shift+Tab' : 'Tab')
    expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBe(true)
  }
  const search = dialog.getByRole('button', { name: 'Search page text', exact: true })
  await tabTo(page, search)
  await page.keyboard.press('Enter')
  await expect(dialog.getByRole('searchbox', { name: 'Find in page text' })).toBeFocused()
  const credit = dialog.locator('summary[aria-label="Drawing credit and licence"]')
  await tabTo(page, credit)
  await page.keyboard.press('Enter')
  await expect(dialog.locator('.data-credit-info')).toHaveAttribute('open', '')
  await page.keyboard.press('Escape')
  await expect(credit).toBeFocused()
  await expect(dialog.locator('.data-credit-info')).not.toHaveAttribute('open')
  await expect(dialog.locator('#data-page-search')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(search).toBeFocused()
  await expect(dialog.locator('#data-page-search')).toHaveCount(0)
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

test('viewer sheet uses its visible title and restores Search after Escape and button close', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockDrawing(page)
  await page.route('**/api/chats', (route) => route.request().method() === 'POST'
    ? route.fulfill({ json: { id: 'keyboard-demo', title: 'Keyboard generated for demo' } })
    : route.fulfill({ json: { chats: [] } }))
  const answer = makeDemoAnswer('How many windows?')
  await page.route('**/api/chats/*/messages', (route) => route.fulfill({
    contentType: 'text/event-stream', body: `event: answer\ndata: ${JSON.stringify(answer)}\n\n`,
  }))
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('How many windows?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const citation = page.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true })
  await citation.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: demoDocument.title, exact: true })
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  const search = dialog.getByRole('button', { name: 'Search sheet', exact: true })
  for (const method of ['Escape', 'button']) {
    await tabTo(page, search)
    await page.keyboard.press('Enter')
    await expect(dialog.getByRole('searchbox', { name: 'Find on sheet' })).toBeFocused()
    if (method === 'Escape') await page.keyboard.press('Escape')
    else {
      await tabTo(page, dialog.getByRole('button', { name: 'Close sheet search' }))
      await page.keyboard.press('Enter')
    }
    await expect(dialog.locator('#viewer-sheet-search')).toHaveCount(0)
    await expect(search).toBeFocused()
    await expect(dialog).toBeVisible()
  }
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(citation).toBeFocused()
})

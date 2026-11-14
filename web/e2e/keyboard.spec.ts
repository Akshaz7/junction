import { expect, test, type Locator, type Page } from '@playwright/test'
import { demoDocument } from '../src/mock/handler'

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

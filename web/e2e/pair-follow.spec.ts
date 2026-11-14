import { devices, expect, test } from '@playwright/test'

// Device pairing: laptop shows "Pair a phone", the phone opens the link, then a brand-new chat asked on the laptop
// opens and streams on the phone with no step on the phone. A stranger phone (not paired) stays out.
const QUESTION = 'How many doors are there?'
test.setTimeout(90_000)
if (process.env.E2E_BASE) test.use({ baseURL: process.env.E2E_BASE })
const { defaultBrowserType: _ignored, ...phoneDevice } = devices['iPhone 15 Pro Max']
const box = 'Ask about your drawings'

test('paired phone auto-opens the laptop new chat; stranger does not; pairing persists and unpairs', async ({ browser, baseURL }) => {
  const desktop = await browser.newContext({ baseURL, viewport: { width: 1400, height: 900 } })
  const phone = await browser.newContext({ ...phoneDevice, baseURL })
  const stranger = await browser.newContext({ ...phoneDevice, baseURL })
  try {
    const [d, p, s] = [await desktop.newPage(), await phone.newPage(), await stranger.newPage()]
    for (const pg of [d, p, s]) {
      await pg.goto('/#/chat')
      await expect(pg.getByRole('combobox', { name: box })).toBeEnabled({ timeout: 20_000 })
    }
    // Laptop: Pair a phone -> link
    await d.getByRole('button', { name: 'Pair a phone' }).click()
    await expect(d.getByRole('img', { name: 'QR code to pair a phone' })).toBeVisible()
    const link = await d.getByLabel('Pairing link').inputValue()
    expect(link).toMatch(/#\/pair\?code=[a-z0-9]{8}$/)
    // Phone scans it
    await p.goto(link)
    await expect(p.getByTestId('pair-notice')).toContainText('Paired')
    await expect(p).toHaveURL(/#\/chat/)
    await expect(p.getByRole('combobox', { name: box })).toBeEnabled({ timeout: 20_000 })
    await p.waitForTimeout(1500) // live socket open
    await s.waitForTimeout(500)

    // Laptop asks in a brand-new chat; the phone shows it streaming within 2 s.
    await d.keyboard.press('Escape')
    await d.getByRole('combobox', { name: box }).fill('@') // a drawing question needs a document attached
    await d.getByRole('option').first().click()
    await d.getByRole('combobox', { name: box }).fill(QUESTION)
    await d.getByRole('combobox', { name: box }).press('Enter')
    await expect(p).toHaveURL(/#\/chat\?chat=/, { timeout: 2000 })
    await expect(p.locator('.pending-exchange, .exchange').first()).toBeVisible({ timeout: 2000 })
    await expect(p.locator('.answer-text').first()).toBeVisible({ timeout: 60_000 })
    // Stranger phone never moves
    await expect(s).not.toHaveURL(/chat=/)

    // Persists across reload; unpair removes it
    await p.reload()
    await expect(p.getByRole('combobox', { name: box })).toBeEnabled({ timeout: 20_000 })
    expect(await p.evaluate(() => window.localStorage.getItem('hologram.pair-codes'))).toContain('"')
    await d.getByRole('button', { name: /Paired|Pair a phone/ }).click()
    await d.getByRole('button', { name: 'Unpair' }).click()
    expect(await d.evaluate(() => window.localStorage.getItem('hologram.pair-codes'))).toBe('[]')
  } finally {
    await desktop.close(); await phone.close(); await stranger.close()
  }
})

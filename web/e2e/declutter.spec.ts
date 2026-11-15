import { expect, test } from '@playwright/test'
import { mkdir } from 'node:fs/promises'

const output = '../results/final/DECLUTTER'
test.use({ reducedMotion: 'reduce' })
test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', (route) => route.fulfill({ status: 404, json: { detail: 'Demo fixture has no live API.' } }))
})

for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test(`two footer controls, keyboard menu and export at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport)
    await page.goto('/e2e/declutter.html')
    const card = page.getByTestId('answer-card')
    const footer = card.locator('.answer-actions')
    await expect(footer.locator(':scope > *')).toHaveCount(2)
    await expect(footer.getByText('Sources', { exact: true })).toBeVisible()
    await expect(footer.getByRole('button', { name: 'Visualise it' })).toBeVisible()
    await expect(card.getByTestId('answer-docs')).toHaveCount(0)
    await expect(card.locator('.evidence-footer').getByTestId('answer-cost')).toHaveText('$0.0058')
    await expect(card.getByRole('button', { name: 'Read aloud' })).toBeHidden()
    await mkdir(output, { recursive: true })
    await page.screenshot({ path: `${output}/footer-${viewport.width}.png`, fullPage: true })
    const more = card.getByLabel('More answer actions')
    await more.focus(); await page.keyboard.press('Enter')
    await expect(card.getByRole('button', { name: 'Read aloud' })).toBeVisible()
    await page.keyboard.press('Tab')
    await expect(card.getByRole('button', { name: 'Read aloud' })).toBeFocused()
    await page.keyboard.press('Escape')
    await expect(more).toBeFocused()
    await expect(card.getByRole('button', { name: 'Read aloud' })).toBeHidden()
    await more.click()
    await page.screenshot({ path: `${output}/menu-${viewport.width}.png`, fullPage: true })
    await card.getByRole('button', { name: 'Export report', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Export site report' })
    await expect(dialog).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(dialog).toHaveCount(0)
    await expect(card.getByRole('button', { name: 'Export report', exact: true })).toBeFocused()
    await card.getByTestId('takeoff-sheet').click()
    await expect(page.getByRole('status').last()).toHaveText('takeoff requested')
    await footer.getByRole('button', { name: 'Visualise it' }).click()
    await expect(page.getByRole('status').last()).toHaveText('3D opened')
    await footer.locator('summary').click()
    await footer.getByRole('button', { name: 'Open citation 1' }).click()
    await expect(page.getByRole('status').last()).toHaveText('citation opened')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  })
}

test('legacy costs and take-off CSV remain reachable', async ({ page }) => {
  await page.goto('/e2e/declutter.html?legacy&takeoff')
  await expect(page.locator('.evidence-footer').getByTestId('answer-cost')).toHaveText('$0.0058')
  await page.getByLabel('More answer actions').click()
  await expect(page.getByTestId('takeoff-sheet')).toHaveCount(0)
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId('takeoff-csv').click()])
  expect(download.suggestedFilename()).toBe('take-off.csv')
})

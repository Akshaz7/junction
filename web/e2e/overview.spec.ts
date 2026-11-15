import { expect, test } from '@playwright/test'

test('overview is a one-screen landing page', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/#/overview')
  const overview = page.getByRole('region', { name: 'Workspace overview', exact: true })
  await expect(overview.getByRole('link', { name: /Start a chat/ })).toBeVisible()
  expect(await overview.locator('.overview-caps li').count()).toBeGreaterThanOrEqual(6)
  expect(await overview.evaluate((el) => el.scrollHeight <= el.clientHeight)).toBe(true)
})

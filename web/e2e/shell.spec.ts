import { expect, test } from '@playwright/test'

test('demo chat and document navigation', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveTitle('Hologram')
  await page.getByRole('button', { name: /Start with the drawing/ }).click()
  await expect(page.getByText('2 windows', { exact: true })).toBeVisible()
  await page.getByText('Sources (1)', { exact: true }).click()
  await expect(page.getByText(/window-001, window-002/)).toBeVisible()
  await page.getByRole('button', { name: 'Data', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Garden room — generated for demo' })).toBeVisible()
  await page.getByRole('searchbox', { name: 'Search documents' }).fill('missing')
  await expect(page.getByText('No documents found.')).toBeVisible()
})

import { expect, test } from '@playwright/test'

test('searching "AC20" lists the AC20 building first', async ({ page }) => {
  await page.goto('/#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill('AC20')
  await expect(page.locator('.data-file-row').first()).toHaveAttribute('data-doc-id', 'ifc_bench__ac20-arc')
})

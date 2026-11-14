import { expect, test } from '@playwright/test'

const ac20 = 'ifc_bench__ac20-arc'
test.setTimeout(120_000)

test('export report dialog closes with Escape and the close button, and focus returns to the trigger', async ({ page }) => {
  await page.goto('/#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(ac20)
  await page.locator(`[data-doc-id="${ac20}"] .data-open-file`).click()
  await page.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  const question = 'How many windows are there?'
  await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill(question)
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const card = page.locator('.exchange').filter({ hasText: question }).last()
  await expect(card.getByTestId('answer-cost')).toBeVisible({ timeout: 60_000 })
  const trigger = card.getByRole('button', { name: 'Export report', exact: true })
  const dialog = page.getByRole('dialog', { name: 'Export site report' })

  await trigger.click()
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()

  await trigger.click()
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Close export report', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(trigger).toBeFocused()
})

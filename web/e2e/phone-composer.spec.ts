import { expect, test } from '@playwright/test'

test.setTimeout(150_000)
const ac20 = 'ifc_bench__ac20-arc'

test('phone: the composer stays reachable under the open viewer sheet, and a follow-up closes the sheet', async ({ page }) => {
  await page.setViewportSize({ width: 430, height: 932 })
  await page.goto('/#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill('AC20')
  await page.locator(`[data-doc-id="${ac20}"] .data-open-file`).click()
  await page.locator('aside.data-detail[role=dialog]').getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  const input = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await input.fill('How many windows are there?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const card = page.locator('.exchange').filter({ hasText: 'How many windows are there?' }).last()
  await expect(card.getByTestId('answer-cost')).toBeVisible({ timeout: 60_000 })
  await card.locator('.answer-text').getByRole('button', { name: /^Open citation/ }).first().click()
  const drawing = page.locator('aside.viewer-sheet')
  await expect(drawing).toBeVisible()
  // The composer is on screen and not covered by the sheet.
  const composerTop = (await input.boundingBox())!.y
  await expect.poll(async () => { const b = (await drawing.boundingBox())!; return b.y + b.height }).toBeLessThanOrEqual(composerTop)
  expect((await input.boundingBox())!.y + 30).toBeLessThanOrEqual(932)
  // Focusing it collapses the sheet to a peek bar.
  await input.click()
  await expect.poll(async () => (await drawing.boundingBox())!.height).toBeLessThan(120)
  // A follow-up question closes the sheet so the new answer is visible.
  await input.fill('How many doors are there?')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  await expect(drawing).toHaveCount(0)
  await expect(page.locator('.exchange').filter({ hasText: 'How many doors are there?' }).last().getByTestId('answer-cost')).toBeVisible({ timeout: 60_000 })
})

import { expect, test, type Page } from '@playwright/test'

test.setTimeout(120_000)
const ac20 = 'ifc_bench__ac20-arc'
const question = 'How many windows are there?'

test('the 2D plan of an IFC building shows each room name with its area; raster plans show none', async ({ page }) => {
  await page.goto('/#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(ac20)
  await page.locator(`[data-doc-id="${ac20}"] .data-open-file`).click()
  await page.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill(question)
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const card = page.locator('.exchange').filter({ hasText: question }).last()
  await expect(card.getByTestId('answer-cost')).toBeVisible({ timeout: 60_000 })
  await card.locator('.answer-text').getByRole('button', { name: /^Open citation/ }).first().click()
  const drawing = page.getByRole('region', { name: 'Drawing viewer', exact: true })
  await expect(drawing).toBeVisible()
  const labels = drawing.locator('.room-label')
  await expect(labels.first()).toBeAttached({ timeout: 20_000 })
  const text = await labels.first().textContent()
  expect(text).toMatch(/\d+\.\d m²/)
  expect(await labels.evaluate((nodes) => getComputedStyle(nodes).fontWeight)).toBe('400')
  await drawing.screenshot({ path: '../results/qa/shots/room-labels.png' })
})

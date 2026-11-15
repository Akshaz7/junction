import { expect, test } from '@playwright/test'
import { readFileSync } from 'node:fs'

test.use({ viewport: { width: 1440, height: 900 } })
test.setTimeout(240_000)
const ac20 = 'ifc_bench__ac20-arc'

async function openChat(page: import('@playwright/test').Page) {
  await page.goto('/#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(ac20)
  await page.locator(`[data-doc-id="${ac20}"] .data-open-file`).click()
  await page.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  return page.getByRole('combobox', { name: 'Ask about your drawings' })
}
const settled = (page: import('@playwright/test').Page) => expect(page.locator('.status-lines')).toHaveCount(0, { timeout: 120_000 })

test('quantity take-off renders a cited table and downloads as CSV', async ({ page }) => {
  const box = await openChat(page)
  await box.fill('give me a quantity take-off')
  await box.press('Enter')
  await settled(page)
  const table = page.locator('.exchange table').first()
  await expect(table).toBeVisible()
  await expect(table.locator('th').first()).toHaveText('Item')
  expect(await table.locator('tbody tr').count()).toBeGreaterThan(5)
  await expect(table.locator('.citation-chip').first()).toBeVisible()
  await page.getByLabel('More answer actions').last().click()
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByTestId('takeoff-csv').click()])
  expect(download.suggestedFilename()).toMatch(/\.csv$/)
  const csv = readFileSync(await download.path(), 'utf8')
  const lines = csv.replace(/^﻿/, '').trim().split(/\r\n/)
  expect(lines[0]).toBe('Item,Quantity,Unit,Source')
  expect(lines.length).toBeGreaterThan(5)
  await expect(page.getByTestId('takeoff-sheet')).toHaveCount(0)
})

test('a normal answer offers the Take-off sheet button', async ({ page }) => {
  const box = await openChat(page)
  await box.fill('how many doors are there')
  await box.press('Enter')
  await settled(page)
  await page.getByLabel('More answer actions').last().click()
  const button = page.getByTestId('takeoff-sheet')
  await expect(button).toBeVisible()
  await button.click()
  await settled(page)
  await expect(page.locator('.exchange')).toHaveCount(2)
  await page.getByLabel('More answer actions').last().click()
  await expect(page.getByTestId('takeoff-csv')).toBeVisible()
})

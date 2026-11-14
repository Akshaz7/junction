import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 1440, height: 900 } })
test.setTimeout(120_000)
const docId = 'cubicasa5k__colorful-11397'
const BUSY = 'This document is still being processed, so there is nothing to answer from yet. Try again in a moment.'

test('a still-processing reply shows "Still reading the drawing…" and retries until the real answer', async ({ page }) => {
  let calls = 0
  await page.route('**/api/chats/*/messages', async (route) => {
    if (route.request().method() !== 'POST') return route.continue()
    calls++
    const response = await route.fetch()
    if (calls > 2) return route.fulfill({ response })
    // The first two replies are the server's "still being processed" answer.
    const body = (await response.text()).split('\n').map((line) => {
      if (!line.startsWith('data:')) return line
      try {
        const payload = JSON.parse(line.slice(5))
        if (payload?.answer?.text_md) return `data: ${JSON.stringify({ ...payload, answer: { ...payload.answer, text_md: BUSY, abstained: true }, citations: [] })}`
      } catch { /* not an answer event */ }
      return line
    }).join('\n')
    return route.fulfill({ response, body })
  })
  await page.goto('/#/data')
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(docId)
  await page.locator(`[data-doc-id="${docId}"] .data-open-file`).click()
  await page.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  const box = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await box.fill('How many windows are there?')
  await box.press('Enter')
  await expect(page.getByText('Still reading the drawing…')).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('.exchange')).toHaveCount(1)
  await expect(page.getByTestId('answer-cost')).toBeVisible({ timeout: 60_000 })
  expect(calls).toBe(3)
  await expect(page.locator('.exchange')).not.toContainText('still being processed')
})

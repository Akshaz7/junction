import { expect, test } from '@playwright/test'

test.setTimeout(60_000)
const box = 'Ask about your drawings'

test('a drawing question with no document is held, not sent; general questions send; picking a document sends it', async ({ page }) => {
  const sent: string[] = []
  page.on('request', (r) => { if (r.method() === 'POST' && /\/api\/chats\/[^/]+\/messages/.test(r.url())) sent.push(r.postData() ?? '') })
  await page.goto('/#/chat')
  const composer = page.getByRole('combobox', { name: box })
  await expect(composer).toBeEnabled()
  await page.getByRole('button', { name: 'Where is it on level N?' }).click()
  await expect(composer).toHaveValue(/level 2/)
  await composer.press('Enter')
  const note = page.getByTestId('need-document')
  await expect(note).toContainText('Add a drawing first')
  await expect(composer).toHaveValue(/level 2/) // text kept
  expect(sent).toHaveLength(0)
  await expect(page.getByRole('status').filter({ hasText: 'Thinking' })).toHaveCount(0)
  await note.getByRole('button', { name: 'Choose a document' }).click()
  const option = page.getByRole('option').first()
  await expect(option).toBeVisible()
  await option.click()
  await expect(page.locator('.pending-exchange, .exchange').first()).toBeVisible({ timeout: 15_000 })
  await expect.poll(() => sent.length).toBeGreaterThan(0)
})

test('general questions with no document still send, and Upload opens the Data upload dialog', async ({ page }) => {
  const sent: string[] = []
  page.on('request', (r) => { if (r.method() === 'POST' && /\/api\/chats\/[^/]+\/messages/.test(r.url())) sent.push(r.postData() ?? '') })
  await page.goto('/#/chat')
  const composer = page.getByRole('combobox', { name: box })
  await expect(composer).toBeEnabled()
  await expect(page.getByRole('button', { name: 'Where is it on level N?' })).toBeEnabled() // documents loaded
  await composer.fill('what can you do?')
  await composer.press('Enter')
  await expect(page.getByTestId('need-document')).toHaveCount(0)
  await expect(page.locator('.pending-exchange, .exchange').first()).toBeVisible({ timeout: 15_000 })

  await page.goto('/#/chat')
  await page.getByRole('button', { name: 'New chat' }).click().catch(() => {})
  await composer.fill('How many doors are there in this drawing?')
  await composer.press('Enter')
  await page.getByTestId('need-document').getByRole('button', { name: 'Upload' }).click()
  await expect(page).toHaveURL(/#\/data/)
  await expect(page.getByRole('dialog', { name: /Upload/ })).toBeVisible()
})

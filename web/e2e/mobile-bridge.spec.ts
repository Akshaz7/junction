import { expect, test } from '@playwright/test'
import type { Document } from '../src/lib/types'
import type { TableSelection } from '../src/lib/ar-bridge'
import { streamedAnswer } from './streamed-answer'

const docId = 'ifc_bench__ac20-arc'
test.use({ viewport: { width: 390, height: 844 } })
test.setTimeout(60_000)

test('phone tabs navigate and native AR receives the real answer evidence in order', async ({ page, request }) => {
  const metadata = await request.get(`http://localhost:8000/api/docs/${docId}`)
  expect(metadata.ok()).toBe(true)
  const doc = await metadata.json() as Document
  const scene = await request.get(`http://localhost:8000/api/docs/${docId}/files/scene.json`)
  expect(scene.ok(), 'The real document needs an existing 3D scene').toBe(true)
  expect((await scene.json()).usdz).toBeTruthy()
  await page.addInitScript(() => {
    const host = window as unknown as { arMessages: unknown[]; webkit: unknown }
    host.arMessages = []
    host.webkit = { messageHandlers: { ar: { postMessage: (message: unknown) => host.arMessages.push(message) } } }
  })
  await page.goto('/#/chat')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  const tabs = page.getByRole('navigation', { name: 'Mobile navigation', exact: true })
  for (const label of ['Overview', 'Chat', 'Changes', 'Data']) {
    await expect(tabs.getByRole('link', { name: label, exact: true })).toBeVisible()
    await tabs.getByRole('link', { name: label, exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`#/${label.toLowerCase()}$`))
  }
  await tabs.getByLabel('More pages', { exact: true }).click()
  await tabs.getByRole('link', { name: 'Accuracy', exact: true }).click()
  await expect(page).toHaveURL(/#\/accuracy$/)
  await tabs.getByRole('link', { name: 'Chat', exact: true }).click()
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill(`@${docId}`)
  await page.getByRole('option').filter({ hasText: doc.title }).click()
  await composer.fill('How many doors are there?')
  const response = page.waitForResponse((res) => res.request().method() === 'POST' && /\/api\/chats\/[^/]+\/messages$/.test(new URL(res.url()).pathname))
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const answer = await streamedAnswer(await response)
  expect(answer.answer.abstained).toBe(false)
  expect(answer.evidence.scene.doc_id).toBe(docId)
  expect(answer.evidence.scene.highlight_item_ids.length).toBeGreaterThan(0)
  const chatId = new URLSearchParams(new URL(page.url()).hash.split('?')[1]).get('chat')
  expect(chatId, 'A new chat must be addressable before opening native AR').toBeTruthy()
  const expected: TableSelection = { doc_id: docId, item_ids: answer.evidence.scene.highlight_item_ids, chat_id: chatId! }
  const recorded = () => page.evaluate(() => (window as unknown as { arMessages: TableSelection[] }).arMessages)
  await page.locator('.answer-actions').getByRole('button', { name: 'Show on table', exact: true }).click()
  expect(await recorded()).toEqual([expected])
  await page.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true }).click()
  const viewer = page.getByRole('dialog', { name: 'Drawing viewer' })
  await viewer.locator('header').getByRole('button', { name: 'Show on table', exact: true }).click()
  expect(await recorded()).toEqual([expected, expected])
  await viewer.getByRole('button', { name: 'Close drawing viewer', exact: true }).click()
  await tabs.getByRole('link', { name: 'Data', exact: true }).click()
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(docId)
  await page.locator(`[data-doc-id="${docId}"] .data-open-file`).click()
  await page.getByRole('complementary', { name: 'Document details' }).locator('header').getByRole('button', { name: 'Show on table', exact: true }).click()
  expect(await recorded()).toEqual([expected, expected, { doc_id: docId, item_ids: [] }])
})

test('a plain phone browser has no native AR button', async ({ page }) => {
  await page.goto('/#/data')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(docId)
  await page.locator(`[data-doc-id="${docId}"] .data-open-file`).click()
  await expect(page.getByRole('button', { name: 'Show on table', exact: true })).toHaveCount(0)
})

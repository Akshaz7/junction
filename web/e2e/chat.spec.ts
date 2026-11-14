import { expect, test } from '@playwright/test'
import type { Document } from '../src/lib/types'
import { streamedAnswer } from './streamed-answer'

const fixtureId = 'cubicasa5k__colorful-11397'

test('real chat streams the fixture answer with bold text, citations and cost', async ({ page, request }) => {
  // Fail if the real fixture is unavailable; this test must never pass on the offline mock.
  const response = await request.get('http://localhost:8000/api/docs')
  expect(response.ok()).toBe(true)
  const grouped = await response.json() as { sources: { docs: Document[] }[] }
  const fixture = grouped.sources.flatMap((source) => source.docs).find((doc) => doc.doc_id === fixtureId)
  expect(fixture, 'Seed the real backend fixture before running this test').toBeTruthy()
  const createdChats: string[] = []
  const sentMessages: { content: string; doc_ids: string[] }[] = []
  page.on('request', (req) => {
    if (req.method() !== 'POST') return
    if (new URL(req.url()).pathname === '/api/chats') createdChats.push(req.url())
    if (/\/api\/chats\/[^/]+\/messages$/.test(new URL(req.url()).pathname)) sentMessages.push(req.postDataJSON())
  })
  await page.goto('/#/chat')
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await expect(page.locator('.starter-card')).toHaveCount(4)
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('@colorful-11397')
  const option = page.getByRole('option').filter({ hasText: fixture!.title })
  await expect(option).toBeVisible()
  await option.click()
  await expect(page.getByLabel('Selected documents')).toContainText(fixture!.title)
  await composer.fill('How many windows are there?')
  const responsePromise = page.waitForResponse((res) => res.request().method() === 'POST' && /\/api\/chats\/[^/]+\/messages$/.test(new URL(res.url()).pathname))
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const payload = await streamedAnswer(await responsePromise)
  expect(payload.answer.abstained).toBe(false)
  expect(payload.answer.unit).toBe('count')
  expect(payload.answer.value).toBeGreaterThan(0)
  const answer = page.locator('.exchange').first()
  await expect(answer.locator('.answer-text strong')).toContainText(`${payload.answer.value}`)
  await expect(answer.locator('.answer-text').getByRole('button', { name: 'Open citation 1' })).toBeVisible()
  await expect(answer.getByTestId('answer-cost')).toHaveText('$0.0000')
  await expect(answer.getByRole('heading', { name: 'Where it is set out' })).toBeVisible()
  await answer.locator('.sources-summary').click()
  await expect(answer.getByText(/window-001, window-002/)).toBeVisible()
  await answer.getByText('Show thought process', { exact: true }).click()
  expect(payload.trace.length).toBeGreaterThan(0)
  await expect(answer.getByText(payload.trace[0].detail, { exact: true })).toBeVisible()
  await answer.locator('.answer-text').getByRole('button', { name: 'Open citation 1' }).click()
  await expect(page.getByText('AI can make mistakes. Verify important information.')).toBeVisible()

  // A follow-up reuses the created chat; unsupported questions are plain abstentions.
  await composer.fill('What is the fire rating of this roof?')
  const followupResponse = page.waitForResponse((res) => res.request().method() === 'POST' && /\/api\/chats\/[^/]+\/messages$/.test(new URL(res.url()).pathname))
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const followup = await streamedAnswer(await followupResponse)
  expect(followup.answer.abstained).toBe(true)
  expect(followup.answer.text_md.trim()).not.toBe('')
  const abstention = page.locator('.exchange').nth(1)
  await expect(abstention.locator('.answer-text')).toHaveText(followup.answer.text_md.replace(/\*\*/g, '').replace(/\s*\[\d+\]/g, ''))
  await expect(abstention.getByRole('button', { name: /Open citation/ })).toHaveCount(0)
  await expect(abstention.locator('.sources-summary')).toHaveCount(0)
  expect(createdChats).toHaveLength(1)
  expect(sentMessages).toEqual([
    { content: 'How many windows are there?', doc_ids: [fixtureId] },
    { content: 'What is the fire rating of this roof?', doc_ids: [fixtureId] },
  ])
})

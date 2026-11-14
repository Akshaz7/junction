import { expect, test } from '@playwright/test'
import type { Answer } from '../src/lib/types'
import { readAnswerStream } from '../src/lib/api'

const api = 'http://localhost:8000'
const docId = 'cubicasa5k__colorful-11397'
test.setTimeout(60_000)

test('History lists real saved chats, Share copies the active link, and New clears the chat', async ({ page, request }) => {
  const title = `W-20 history ${Date.now()}`
  const created = await request.post(`${api}/api/chats`, { data: { doc_ids: [docId], title } })
  expect(created.ok()).toBe(true)
  const { id } = await created.json() as { id: string }
  const response = await request.post(`${api}/api/chats/${id}/messages`, { data: { content: 'How many windows are there?', doc_ids: [docId] } })
  expect(response.ok()).toBe(true)
  const answer: Answer = await readAnswerStream(new Response(await response.text()), { onStatus: () => {}, onTrace: () => {} })
  const another = await request.post(`${api}/api/chats`, { data: { doc_ids: [docId], title: `${title} second` } })
  expect(another.ok()).toBe(true)
  const { id: secondId } = await another.json() as { id: string }
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: {
      writeText: async (value: string) => { (window as Window & { copiedLink?: string }).copiedLink = value },
    } })
  })
  await page.goto('/#/chat')
  const newChat = page.getByRole('button', { name: 'New chat', exact: true })
  const share = page.getByRole('button', { name: 'Share', exact: true })
  await expect(newChat).toBeEnabled()
  await expect(newChat).toHaveCSS('opacity', '1')
  const history = page.getByRole('button', { name: 'History', exact: true })
  await history.click()
  const panel = page.getByRole('dialog', { name: 'Chat history', exact: true })
  const saved = panel.getByRole('link').filter({ hasText: title }).filter({ has: page.locator(`time`) })
  await expect(saved).toHaveCount(2)
  const target = panel.locator(`a[href="#/chat/${id}"]`)
  await expect(target).toContainText(title)
  await expect(target.locator('time')).toHaveAttribute('datetime', /\d{4}-\d\d-\d\dT/)
  await expect(panel.locator(`a[href="#/chat/${secondId}"]`)).toBeVisible()
  await target.click()
  await expect(page).toHaveURL(new RegExp(`#/chat/${id}$`))
  await expect(panel).toHaveCount(0)
  await expect(page.locator('.question-bubble')).toContainText(answer.question)
  await expect(page.locator('.answer-text')).toBeVisible()
  await expect(page.getByLabel('Selected documents')).toBeVisible()
  await expect(share).toBeEnabled()
  await expect(share).toHaveCSS('opacity', '1')
  await share.click()
  await expect(page.getByRole('status').filter({ hasText: 'Link copied' })).toBeVisible()
  expect(await page.evaluate(() => (window as Window & { copiedLink?: string }).copiedLink)).toBe(page.url())

  // On a phone the same saved chat uses the native share sheet when supported.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.evaluate(() => Object.defineProperty(navigator, 'share', { configurable: true, value: async (data: ShareData) => {
    (window as Window & { sharedLink?: string }).sharedLink = data.url
  } }))
  await share.click()
  expect(await page.evaluate(() => (window as Window & { sharedLink?: string }).sharedLink)).toBe(page.url())
  await page.setViewportSize({ width: 1280, height: 800 })

  await page.locator('.answer-text').getByRole('button', { name: `Open citation ${answer.citations[0].n}`, exact: true }).click()
  await expect(page.getByRole('region', { name: 'Drawing viewer', exact: true })).toBeVisible()
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('Unsent question')
  await newChat.click()
  await expect(page).toHaveURL(/#\/chat$/)
  await expect(composer).toHaveValue('')
  await expect(page.locator('.exchange')).toHaveCount(0)
  await expect(page.getByLabel('Selected documents')).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Drawing viewer', exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Where shall we start?', exact: true })).toBeVisible()
})

test('History reports a failed read and can be reopened to retry', async ({ page }) => {
  let fail = true
  await page.route('**/api/chats', (route) => route.fulfill(fail
    ? { status: 503, json: { detail: 'Unavailable' } }
    : { json: { chats: [] } }))
  await page.goto('/#/chat')
  const history = page.getByRole('button', { name: 'History', exact: true })
  await history.click()
  const panel = page.getByRole('dialog', { name: 'Chat history', exact: true })
  await expect(panel.getByRole('alert')).toContainText('Saved chats could not be loaded.')
  await page.keyboard.press('Escape')
  await expect(panel).toHaveCount(0)
  await expect(history).toBeFocused()
  fail = false
  await history.click()
  await expect(panel).toContainText('No saved chats yet.')
})

test('a saved snapshot keeps the streamed answer citation focused and its details open', async ({ page }) => {
  const { demoDocument, makeDemoAnswer } = await import('../src/mock/handler')
  const answer = makeDemoAnswer('How many windows are there?')
  const notifications: ((data: string) => void)[] = []
  await page.routeWebSocket('**/ws', (socket) => { notifications.push((data) => socket.send(data)) })
  await page.route('**/api/docs', (route) => route.fulfill({ json: { sources: [{ source: 'demo', docs: [demoDocument] }] } }))
  await page.route('**/api/chats', (route) => route.fulfill({ json: { id: 'stable-answer-chat' } }))
  await page.route('**/api/chats/stable-answer-chat/messages', (route) => route.fulfill({
    contentType: 'text/event-stream', body: `event: answer\ndata: ${JSON.stringify(answer)}\n\n`,
  }))
  let snapshots = 0
  await page.route('**/api/chats/stable-answer-chat', (route) => {
    snapshots++
    return route.fulfill({ json: { id: 'stable-answer-chat', doc_id: demoDocument.doc_id, messages: [
      { id: 'saved-user-id', role: 'user', content: answer.question, answer: null },
      { id: 'saved-assistant-id', role: 'assistant', content: answer.answer.text_md,
        answer: { ...answer, trace: [...answer.trace, { step: 'sync', detail: 'Saved snapshot loaded.', ms: 0, model: null, cost_usd: 0 }] } },
    ] } })
  })
  await page.goto('/#/chat')
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('@') // a drawing question needs a document attached
  await page.getByRole('option').first().click()
  await composer.fill(answer.question)
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const card = page.locator('.exchange').filter({ has: page.locator('.answer-text') })
  await expect(card).toHaveCount(1)
  const details = card.locator('.thought-process')
  await details.locator('summary').click()
  const citation = card.locator('.answer-text').getByRole('button', { name: 'Open citation 1', exact: true })
  await citation.focus()
  // The persisted user ID differs from the answer ID used by the SSE exchange.
  // A socket echo must preserve the exact control, focus, and native disclosure.
  await citation.evaluate((node) => node.setAttribute('data-retained-control', 'true'))
  const before = snapshots
  await expect.poll(() => notifications.length).toBeGreaterThan(0)
  notifications.forEach((notify) => notify(JSON.stringify({ type: 'chat.message', chat_id: 'stable-answer-chat', message_id: 'saved-assistant-id', role: 'assistant' })))
  await expect.poll(() => snapshots).toBeGreaterThan(before)
  await expect(details).toContainText('Saved snapshot loaded.')
  await expect(citation).toHaveAttribute('data-retained-control', 'true')
  await expect(citation).toBeFocused()
  await expect(details).toHaveAttribute('open', '')
  await expect(card).toHaveCount(1)
})

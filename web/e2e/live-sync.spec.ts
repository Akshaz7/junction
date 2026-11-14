import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import { streamedAnswer } from './streamed-answer'

const docId = 'cubicasa5k__colorful-11397'
test.setTimeout(60_000)

async function openChat(context: BrowserContext, chatId: string) {
  const page = await context.newPage()
  let snapshots = 0
  page.on('response', (response) => {
    if (response.ok() && new URL(response.url()).pathname === `/api/chats/${chatId}`) snapshots++
  })
  await page.goto(`/#/chat?chat=${chatId}`)
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  // The second snapshot follows the real socket's open event. Sending before it
  // arrives can miss notifications while the backend is accepting the socket.
  await expect.poll(() => snapshots, { timeout: 15_000 }).toBeGreaterThanOrEqual(2)
  await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeEnabled()
  return page
}

async function sendAndMeasure(sender: Page, receiver: Page, question: string) {
  await sender.getByRole('combobox', { name: 'Ask about your drawings' }).fill(question)
  const response = sender.waitForResponse((res) => res.request().method() === 'POST' && /\/api\/chats\/[^/]+\/messages$/.test(new URL(res.url()).pathname))
  const start = performance.now()
  const receivedQuestion = receiver.locator('.question-bubble').filter({ hasText: question }).last()
  await sender.getByRole('button', { name: 'Send question', exact: true }).click()
  await expect(receivedQuestion).toBeVisible({ timeout: 2000 })
  const questionMs = performance.now() - start
  expect(questionMs, 'Remote question must appear within two seconds').toBeLessThan(2000)
  const answer = await streamedAnswer(await response)
  expect(answer.answer.abstained).toBe(false)
  const exchange = receiver.locator('.exchange').filter({ has: receiver.getByText(question, { exact: true }) }).last()
  await expect(exchange.locator('.answer-text')).toHaveText(answer.answer.text_md.replace(/\*\*/g, '').replace(/\[(\d+)\]/g, '$1'), { timeout: 2000 })
  const answerMs = performance.now() - start
  expect(answerMs, 'Remote final count answer must appear within two seconds of sending').toBeLessThan(2000)
  await expect(receiver.locator('.pending-exchange')).toHaveCount(0)
  await expect(sender.locator('.question-bubble').filter({ hasText: question })).toHaveCount(1)
  await expect(receiver.locator('.question-bubble').filter({ hasText: question })).toHaveCount(1)
  return { questionMs, answerMs }
}

test('real messages and final answers sync between two independent devices in under two seconds', async ({ browser, request, baseURL }, testInfo) => {
  const created = await request.post('http://localhost:8000/api/chats', { data: { doc_ids: [docId], title: 'Live sync verification' } })
  expect(created.ok()).toBe(true)
  const { id } = await created.json() as { id: string }
  const a = await browser.newContext({ baseURL }), b = await browser.newContext({ baseURL })
  try {
    const pageA = await openChat(a, id), pageB = await openChat(b, id)
    const forward = await sendAndMeasure(pageA, pageB, 'How many windows are there?')
    const reverse = await sendAndMeasure(pageB, pageA, 'How many doors are there?')
    await testInfo.attach('live-sync-times', { contentType: 'application/json', body: JSON.stringify({ forward, reverse }) })
  } finally { await a.close(); await b.close() }
})

test('the overview chat list refreshes when another device asks a question', async ({ browser, request, baseURL }) => {
  const receiver = await browser.newContext({ baseURL })
  try {
    const page = await receiver.newPage()
    let snapshots = 0
    page.on('response', (response) => { if (response.ok() && new URL(response.url()).pathname === '/api/chats') snapshots++ })
    await page.goto('/#/overview')
    await expect.poll(() => snapshots, { timeout: 15_000 }).toBeGreaterThanOrEqual(2)
    const title = `Live overview ${Date.now()}`
    const created = await request.post('http://localhost:8000/api/chats', { data: { doc_ids: [docId], title } })
    expect(created.ok()).toBe(true)
    const { id } = await created.json() as { id: string }
    const answered = await request.post(`http://localhost:8000/api/chats/${id}/messages`, { data: { content: 'How many windows are there?', doc_ids: [docId] } })
    expect(answered.ok()).toBe(true)
    const link = page.locator(`[data-testid="overview-chat"][href="#/chat?chat=${id}"]`)
    await expect(link).toBeVisible({ timeout: 2000 })
    await expect(link.locator('.overview-answer')).not.toHaveText('No answer yet.', { timeout: 2000 })
  } finally { await receiver.close() }
})

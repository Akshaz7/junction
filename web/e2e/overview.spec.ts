import { expect, test, type APIRequestContext, type Locator } from '@playwright/test'

// Real API only. The LEAD wires #/overview before running this spec.
async function read(request: APIRequestContext, path: string, optional = false) {
  const response = await request.get(path)
  if (optional && response.status() === 404) return null
  expect(response.ok(), `${path}: ${response.status()}`).toBe(true)
  return response.json()
}

async function loaded(section: Locator) { await expect(section).toHaveAttribute('aria-busy', 'false') }

test('overview sections match the real workspace API', async ({ page, request }) => {
  const [changes, findings, chats] = await Promise.all([
    read(request, '/api/changes'), read(request, '/api/findings', true), read(request, '/api/chats'),
  ])
  await page.goto('/#/overview')
  const overview = page.getByRole('region', { name: 'Workspace overview', exact: true })
  await expect(overview).toBeVisible()
  const changesSection = overview.getByRole('region', { name: "This week's changes", exact: true })
  const findingsSection = overview.getByRole('region', { name: 'Open findings', exact: true })
  const chatsSection = overview.getByRole('region', { name: 'Latest answers', exact: true })
  const accuracySection = overview.getByRole('region', { name: 'Accuracy', exact: true })
  for (const section of [changesSection, findingsSection, chatsSection]) await loaded(section)

  const week = await page.evaluate(() => {
    const start = new Date()
    start.setHours(0, 0, 0, 0)
    start.setDate(start.getDate() - (start.getDay() + 6) % 7)
    return { start: start.getTime(), now: Date.now() }
  })
  // Test uploads and repeats are hidden, titles are cleaned: check the page, not the raw feed.
  const changeRows = changesSection.getByTestId('overview-change')
  if (!(await changeRows.count())) await expect(changesSection).toContainText('No changes this week.')
  for (const row of await changeRows.all()) {
    await expect(row).toHaveAttribute('href', '#/changes')
    const text = (await row.innerText()).toLowerCase()
    expect(text).not.toMatch(/\b(smoke|qa|audit|w65|web3)[-_]|generated for demo|\.pdf|\d{10,}/)
    await expect(row.locator('span')).toHaveText(/^New (upload|version)/)
  }

  const findingRows = findings?.findings || []
  if (!findingRows.length) await expect(findingsSection).toContainText('No findings yet.')
  else {
    const cards = findingsSection.getByTestId('overview-finding')
    expect(await cards.count()).toBeGreaterThan(0)
    expect(await cards.count()).toBeLessThanOrEqual(3)
    await expect(findingsSection).not.toContainText('This is an inference')
    await expect(findingsSection).not.toContainText(/\bsuggestion\b/)
    for (const card of await cards.all()) await expect(card.locator('details')).not.toHaveAttribute('open', '')
  }

  const rows = chatsSection.getByTestId('overview-chat')
  if (!(await rows.count())) await expect(chatsSection).toContainText('No answers yet.')
  await expect(chatsSection).not.toContainText('No answer yet.')
  await expect(chatsSection).not.toContainText('Cost:')
  const questions = await rows.locator('strong').allInnerTexts()
  expect(new Set(questions.map((q) => q.trim().toLowerCase())).size).toBe(questions.length)

  await expect(accuracySection).toHaveCount(0) // benchmarks are not shown in the app (W-55)
  if (await rows.count()) {
    const question = (await rows.first().locator('strong').innerText()).trim()
    await rows.first().click()
    await expect(page).toHaveURL(/#\/chat\?chat=/)
    await expect(page.locator('.question-bubble').filter({ hasText: question }).first()).toBeVisible()
  }
})

test('overview starter cards show all four construction prompts and fit a phone', async ({ page }) => {
  // Starting a real chat from each card is covered live in data-changes.spec.ts.
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#/overview')
  const starters = page.getByRole('region', { name: 'Start a question', exact: true })
  await expect(starters.locator('.overview-starter')).toHaveCount(4)
  for (const title of ['Draft claim', 'Meeting prep', 'Plan work phase', 'Review contract']) await expect(starters.getByRole('button', { name: title, exact: true })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
})

test('chat links load directly, switch saved conversations, and keep follow-ups in the saved chat', async ({ page }) => {
  // These saved-chat fixtures also receive the socket-open snapshot refresh.
  await page.routeWebSocket('**/ws', () => {})
  let otherSnapshots = 0
  page.on('response', (response) => {
    if (response.ok() && new URL(response.url()).pathname === '/api/chats/other-chat') otherSnapshots++
  })
  const { demoDocument, makeDemoAnswer } = await import('../src/mock/handler')
  const savedAnswer = makeDemoAnswer('How many windows are there?')
  const saved = {
    id: 'saved-chat', doc_id: demoDocument.doc_id,
    messages: [
      { id: 'q1', role: 'user', content: savedAnswer.question, answer: null },
      { id: 'a1', role: 'assistant', content: savedAnswer.answer.text_md, answer: savedAnswer },
      { id: 'q2', role: 'user', content: 'What about doors?', answer: null },
      { id: 'a2', role: 'assistant', content: 'No door data in this drawing.', answer: null },
    ],
  }
  const posts: string[] = []
  await page.route('**/api/docs', (route) => route.fulfill({ json: { sources: [{ source: 'demo', docs: [demoDocument] }] } }))
  await page.route('**/api/chats/saved-chat', (route) => route.fulfill({ json: saved }))
  await page.route('**/api/chats/other-chat', (route) => route.fulfill({ json: {
    id: 'other-chat', doc_id: demoDocument.doc_id,
    messages: [{ id: 'q3', role: 'user', content: 'Where are the stairs?', answer: null }],
  } }))
  await page.route('**/api/chats/*/messages', async (route) => {
    posts.push(new URL(route.request().url()).pathname)
    const { content } = route.request().postDataJSON()
    await route.fulfill({ contentType: 'text/event-stream', body: `event: answer\ndata: ${JSON.stringify(makeDemoAnswer(content))}\n\n` })
  })
  await page.goto('/#/chat?chat=saved-chat')
  await expect(page.locator('.question-bubble')).toHaveText([savedAnswer.question, 'What about doors?'])
  await expect(page.locator('.answer-text').last()).toHaveText('No door data in this drawing.')
  await expect(page.getByLabel('Selected documents')).toContainText(demoDocument.title)
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await composer.fill('How many windows are there?')
  await page.getByRole('button', { name: 'Send question' }).click()
  await expect(page.locator('.exchange')).toHaveCount(3)
  expect(posts).toEqual(['/api/chats/saved-chat/messages'])

  await page.evaluate(() => { location.hash = '/chat?chat=other-chat' })
  await expect.poll(() => otherSnapshots).toBeGreaterThanOrEqual(2)
  await expect(page.locator('.question-bubble')).toHaveText(['Where are the stairs?'])
  await expect(page.getByRole('alert').filter({ hasText: 'The answer did not arrive' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry' })).toBeVisible()
  await expect(page.locator('.pending-exchange')).toHaveCount(0)
  await expect(composer).toBeEnabled()
  const question = 'Where is A+B?'
  await page.evaluate((text) => { location.hash = `/chat?question=${encodeURIComponent(text)}` }, question)
  await expect(composer).toHaveValue(question)
  await expect(page.locator('.exchange')).toHaveCount(0)
  expect(posts).toHaveLength(1)
  await page.getByRole('button', { name: 'New chat', exact: true }).click()
  await expect(page).toHaveURL(/#\/chat$/)
  await expect(composer).toHaveValue('')
})

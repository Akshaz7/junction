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
  const [changes, findings, chats, bench] = await Promise.all([
    read(request, '/api/changes'), read(request, '/api/findings', true), read(request, '/api/chats'), read(request, '/api/bench/latest', true),
  ])
  await page.goto('/#/overview')
  const overview = page.getByRole('region', { name: 'Workspace overview', exact: true })
  await expect(overview).toBeVisible()
  const changesSection = overview.getByRole('region', { name: "This week's changes", exact: true })
  const findingsSection = overview.getByRole('region', { name: 'Open findings', exact: true })
  const chatsSection = overview.getByRole('region', { name: 'Latest answers', exact: true })
  const accuracySection = overview.getByRole('region', { name: 'Accuracy', exact: true })
  for (const section of [changesSection, findingsSection, chatsSection, accuracySection]) await loaded(section)

  const week = await page.evaluate(() => {
    const start = new Date()
    start.setHours(0, 0, 0, 0)
    start.setDate(start.getDate() - (start.getDay() + 6) % 7)
    return { start: start.getTime(), now: Date.now() }
  })
  const recentChanges = changes.changes.filter((row: { created_at: string }) => Date.parse(row.created_at) >= week.start && Date.parse(row.created_at) <= week.now)
    .sort((a: { created_at: string }, b: { created_at: string }) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 5)
  await expect(changesSection.getByTestId('overview-change')).toHaveCount(recentChanges.length)
  if (!recentChanges.length) await expect(changesSection).toContainText('No changes this week.')
  for (const [index, change] of recentChanges.entries()) {
    const row = changesSection.getByTestId('overview-change').nth(index)
    await expect(row).toHaveAttribute('href', '#/changes')
    if (change.summary.title || change.summary.headline) await expect(row.locator('strong')).toHaveText(change.summary.title || change.summary.headline)
    await expect(row.locator('time')).toHaveAttribute('datetime', change.created_at)
    if (change.summary.generated_for_demo) await expect(row).toContainText('generated for demo')
  }

  const findingRows = findings?.findings || []
  if (!findingRows.length) await expect(findingsSection).toContainText('No findings yet.')
  else {
    for (const severity of ['violation', 'suggestion', 'info']) {
      const count = findingRows.filter((row: { severity: string }) => row.severity === severity).length
      await expect(findingsSection.getByTestId(`overview-${severity}-count`)).toHaveText(String(count))
    }
    const rank: Record<string, number> = { violation: 0, suggestion: 1, info: 2 }
    const top = [...findingRows].sort((a, b) => rank[a.severity] - rank[b.severity] || Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 3)
    await expect(findingsSection.getByTestId('overview-finding')).toHaveCount(top.length)
    for (const [index, finding] of top.entries()) await expect(findingsSection.getByTestId('overview-finding').nth(index)).toContainText(finding.message)
  }

  const recentChats = [...chats.chats].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)).slice(0, 5)
  await expect(chatsSection.getByTestId('overview-chat')).toHaveCount(recentChats.length)
  if (!recentChats.length) await expect(chatsSection).toContainText('No answers yet.')
  for (const [index, chat] of recentChats.entries()) {
    const detail = await read(request, `/api/chats/${encodeURIComponent(chat.id)}`)
    const messages = detail.messages as { role: string; content: string; answer: { answer: { text_md: string }; cost: { usd_total: number } } | null }[]
    const questionIndex = messages.map((message) => message.role).lastIndexOf('user')
    const answer = messages.slice(questionIndex + 1).reverse().find((message) => message.role === 'assistant')
    const row = chatsSection.getByTestId('overview-chat').nth(index)
    await expect(row).toHaveAttribute('href', `#/chat?chat=${encodeURIComponent(chat.id)}`)
    await expect(row.locator('strong')).toHaveText(questionIndex >= 0 ? messages[questionIndex].content : chat.title || 'Untitled chat')
    const text = answer ? (answer.answer?.answer.text_md || answer.content).replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/[*_`#>]/g, '').replace(/\s+/g, ' ').trim() : 'No answer yet.'
    await expect(row.locator('.overview-answer')).toHaveText(text)
    const cost = answer?.answer?.cost.usd_total
    await expect(row.locator('small')).toHaveText(`Cost: ${typeof cost === 'number' ? `$${cost.toFixed(Math.abs(cost) < .01 ? 6 : 2)}` : 'Not available'}`)
  }

  if (!bench) await expect(accuracySection).toContainText('No bench run yet.')
  else {
    const total = bench.data.cells?.['ALL x ALL']
    await expect(accuracySection.getByTestId('overview-accuracy')).toHaveText(typeof total?.accuracy === 'number' ? `${(total.accuracy * 100).toFixed(1)}%` : 'not scored')
    const cost = total?.cost_usd_per_answer
    await expect(accuracySection.getByTestId('overview-cost-per-answer')).toHaveText(typeof cost === 'number' ? `$${cost.toFixed(Math.abs(cost) < .01 ? 6 : 2)}` : 'Not available')
    if (bench.data.fake === true) await expect(accuracySection).toContainText('test run, fake model')
    await expect(accuracySection).toContainText(bench.file)
  }
  await expect(accuracySection.getByRole('link')).toHaveAttribute('href', '#/accuracy')
  if (recentChats.length) {
    await chatsSection.getByTestId('overview-chat').first().click()
    await expect(page).toHaveURL(new RegExp(`#/chat\\?chat=${encodeURIComponent(recentChats[0].id)}$`))
    const detail = await read(request, `/api/chats/${encodeURIComponent(recentChats[0].id)}`)
    const question = [...detail.messages].reverse().find((message) => message.role === 'user')
    if (question) await expect(page.locator('.question-bubble').last()).toHaveText(question.content)
  }
})

test('overview starter links carry all four questions and fit a phone', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/#/overview')
  const starters = page.getByRole('region', { name: 'Start a question', exact: true })
  const questions = ['How many windows are there?', 'What is the area of this room?', 'Where is the stair core on level 2?', 'What does this drawing say about the doors?']
  await expect(starters.getByRole('link')).toHaveCount(4)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  for (const question of questions) {
    const link = starters.getByRole('link', { name: question, exact: true })
    await expect(link).toHaveAttribute('href', `#/chat?question=${encodeURIComponent(question)}`)
    await link.click()
    await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toHaveValue(question)
    await page.goto('/#/overview')
  }
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
  await expect(page.locator('.answer-text')).toHaveText('No answer yet.')
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

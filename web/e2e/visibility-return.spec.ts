import { expect, test, type BrowserContext, type Page, type WebSocketRoute } from '@playwright/test'

const docId = 'cubicasa5k__colorful-11397'
const draft = 'Keep this unsent draft'
test.use({ viewport: { width: 390, height: 844 } })

async function background(page: Page, context: BrowserContext) {
  await page.evaluate(() => {
    // Native AR dismisses the keyboard before covering the retained WKWebView.
    (document.activeElement as HTMLElement | null)?.blur()
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' })
    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }))
  })
  await context.setOffline(true)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
}

async function foreground(page: Page, context: BrowserContext) {
  await page.evaluate(() => {
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'visible' })
    document.dispatchEvent(new Event('visibilitychange'))
    window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }))
  })
  await context.setOffline(false)
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
}

async function assertDraft(page: Page, href: string, timeOrigin: number) {
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await expect(composer).toBeVisible()
  await expect(composer).toBeInViewport()
  await expect(composer).toBeEnabled()
  await expect(composer).toHaveValue(draft)
  await expect(page.getByRole('button', { name: 'Send question', exact: true })).toBeEnabled()
  expect(page.url()).toBe(href)
  expect(await page.evaluate(() => performance.timeOrigin)).toBe(timeOrigin)
}

for (const saved of [false, true]) {
  test(`${saved ? 'saved' : 'new'} chat keeps its visible, enabled draft after background and socket recovery`, async ({ page, context, request }) => {
    let chatId = ''
    if (saved) {
      const response = await request.post('http://localhost:8000/api/chats', {
        data: { doc_ids: [docId], title: 'Visibility return verification' },
      })
      expect(response.ok()).toBe(true)
      chatId = (await response.json() as { id: string }).id
    }
    let snapshots = 0
    let socketCloses = 0
    page.on('response', (response) => {
      if (response.ok() && new URL(response.url()).pathname === `/api/chats/${chatId}`) snapshots++
    })
    page.on('websocket', (socket) => socket.on('close', () => socketCloses++))
    await page.goto(saved ? `/#/chat?chat=${chatId}` : '/#/chat')
    await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
    if (saved) await expect.poll(() => snapshots).toBeGreaterThanOrEqual(2)
    await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill(draft)
    const href = page.url()
    const timeOrigin = await page.evaluate(() => performance.timeOrigin)
    const before = snapshots
    await background(page, context)
    if (saved) await expect.poll(() => socketCloses).toBeGreaterThan(0)
    await foreground(page, context)
    if (saved) await expect.poll(() => snapshots).toBeGreaterThan(before)
    await assertDraft(page, href, timeOrigin)
    await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill(`${draft} — still editable`)
    await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toHaveValue(`${draft} — still editable`)
  })
}

test('an interrupted remote request cannot disable the draft after reconnect', async ({ page, context }) => {
  // Controlled interrupted-request fixture generated for demo. No question is
  // submitted to a model: its final notification is deliberately never sent.
  const chatId = 'visibility-generated-chat'
  const messageId = 'visibility-generated-message'
  let pending = false
  let socket: WebSocketRoute | undefined
  let connections = 0
  let snapshots = 0
  await page.route(`**/api/chats/${chatId}`, async (route) => {
    snapshots++
    await route.fulfill({ json: { id: chatId, doc_id: docId, messages: pending ? [
      { id: messageId, role: 'user', content: 'Interrupted question generated for demo', answer: null },
    ] : [] } })
  })
  await page.routeWebSocket((url) => url.pathname === '/ws' && !url.search, (route) => { socket = route; connections++ })
  await page.goto(`/#/chat?chat=${chatId}`)
  await expect(page.getByText('Connected workspace', { exact: true })).toBeVisible()
  await expect.poll(() => snapshots).toBeGreaterThanOrEqual(2)
  await page.getByRole('combobox', { name: 'Ask about your drawings' }).fill(draft)
  const href = page.url()
  const timeOrigin = await page.evaluate(() => performance.timeOrigin)
  pending = true
  socket!.send(JSON.stringify({ type: 'chat.message', chat_id: chatId, message_id: messageId, role: 'user' }))
  await expect(page.locator('.pending-exchange')).toBeVisible()
  const before = snapshots
  const previousConnections = connections
  await background(page, context)
  await foreground(page, context)
  await expect.poll(() => connections).toBeGreaterThan(previousConnections)
  await expect.poll(() => snapshots).toBeGreaterThan(before)
  await expect(page.locator('.pending-exchange')).toHaveCount(0)
  await assertDraft(page, href, timeOrigin)
})

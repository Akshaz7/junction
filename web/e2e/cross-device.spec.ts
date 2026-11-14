import { devices, expect, test, type Browser, type BrowserContext, type Page } from '@playwright/test'

// Cross-device live demo flow: a judge asks on the laptop, the phone (iPhone 15 Pro Max emulation) follows
// live. API base: E2E_API (deployed run) or the local API. Test chats are the only writes.
const API = process.env.E2E_API ?? 'http://localhost:8000'
const docId = 'ifc_bench__ac20-arc'
const SLOW_QUESTION = 'What does this drawing say about the doors?' // model-backed, several seconds
const QUESTION = 'How many doors are there?' // code-solved, cited
test.setTimeout(90_000)
// Deployed run: E2E_BASE=https://hologram-khaki.vercel.app E2E_API=https://hologram-khaki.vercel.app npx playwright test e2e/cross-device.spec.ts
if (process.env.E2E_BASE) test.use({ baseURL: process.env.E2E_BASE })

const { defaultBrowserType: _ignored, ...phoneDevice } = devices['iPhone 15 Pro Max']

async function contexts(browser: Browser, baseURL: string | undefined) {
  const desktop = await browser.newContext({ baseURL, viewport: { width: 1400, height: 900 } })
  const phone = await browser.newContext({ ...phoneDevice, baseURL })
  // Native AR bridge stub, as in the iOS WKWebView: records what the phone asks native AR to show.
  await phone.addInitScript(() => {
    const host = window as unknown as { arMessages: unknown[]; webkit: unknown; __seen: Record<string, number> }
    host.arMessages = []
    host.__seen = {}
    host.webkit = { messageHandlers: { ar: { postMessage: (m: unknown) => host.arMessages.push(m) } } }
    // Record when the first in-progress state and the final answer appear on this page.
    new MutationObserver(() => {
      const t = performance.now()
      if (!host.__seen.pending && document.querySelector('.pending-exchange')) host.__seen.pending = t
      if (!host.__seen.status && document.querySelector('.pending-exchange .status-lines')) host.__seen.status = t
      if (!host.__seen.answer && document.querySelector('.exchange:not(.pending-exchange) .answer-text')) host.__seen.answer = t
    }).observe(document, { childList: true, subtree: true, characterData: true })
  })
  return { desktop, phone }
}

async function ready(page: Page, hash: string) {
  await page.goto(`/#${hash}`)
  await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeEnabled({ timeout: 20_000 })
  await page.waitForTimeout(1500) // let the live socket open and the reconnect snapshot land
}

// Pair the phone with the laptop first (W-39), as a judge would by scanning the QR; no-op on builds without it.
async function pair(d: Page, p: Page) {
  const pairBtn = d.getByRole('button', { name: 'Pair a phone' })
  if (!(await pairBtn.count())) return
  await pairBtn.click()
  const link = await d.getByLabel('Pairing link').inputValue()
  await p.goto(link)
  await expect(p.getByTestId('pair-notice')).toContainText('Paired')
  await d.keyboard.press('Escape')
}

async function newChat(request: BrowserContext['request'], title: string) {
  const created = await request.post(`${API}/api/chats`, { data: { doc_ids: [docId], title } })
  expect(created.ok()).toBe(true)
  return (await created.json() as { id: string }).id
}

test('desktop asks; phone sees in-progress states before the final answer with citations; phone posts back live', async ({ browser, baseURL }, testInfo) => {
  const { desktop, phone } = await contexts(browser, baseURL)
  try {
    const id = await newChat(desktop.request, `Cross-device ${Date.now()}`)
    const [d, p] = [await desktop.newPage(), await phone.newPage()]
    await ready(d, `/chat?chat=${id}`)
    await ready(p, `/chat?chat=${id}`)
    await pair(d, p)
    await ready(p, `/chat?chat=${id}`)

    // 1) A slow question: the phone must show the question, status lines and trace BEFORE the answer.
    await d.getByRole('combobox', { name: 'Ask about your drawings' }).fill(SLOW_QUESTION)
    const t0 = Date.now()
    await d.getByRole('button', { name: 'Send question', exact: true }).click()
    await expect(p.locator('.pending-exchange .question-bubble')).toHaveText(SLOW_QUESTION, { timeout: 5000 })
    const firstEventMs = Date.now() - t0
    console.log(JSON.stringify({ firstEventMs }))
    await expect(p.locator('.pending-exchange .status-lines')).toBeVisible()
    await expect(p.locator('.pending-exchange .answer-detail')).toBeVisible({ timeout: 5000 }) // trace steps streamed in
    const slowCard = p.locator('.exchange:not(.pending-exchange)').filter({ hasText: SLOW_QUESTION }).last()
    await expect(slowCard.locator('.answer-text')).toBeVisible({ timeout: 40_000 })
    const answerMs = Date.now() - t0
    const seen = await p.evaluate(() => (window as unknown as { __seen: Record<string, number> }).__seen)
    expect(seen.pending, 'in-progress state observed on the phone').toBeTruthy()
    expect(seen.pending, 'in-progress before final answer').toBeLessThan(seen.answer)
    await expect(p.locator('.pending-exchange')).toHaveCount(0)
    await expect(d.locator('.question-bubble').filter({ hasText: SLOW_QUESTION })).toHaveCount(1)
    await expect(p.locator('.question-bubble').filter({ hasText: SLOW_QUESTION })).toHaveCount(1)

    // 2) A cited count answer reaches the phone with citations, as a follow-up in the SAME chat (the judges' flow).
    const id2c = id
    await d.getByRole('combobox', { name: 'Ask about your drawings' }).fill(QUESTION)
    await d.getByRole('button', { name: 'Send question', exact: true }).click()
    const answerCard = p.locator('.exchange:not(.pending-exchange)').filter({ hasText: QUESTION }).last()
    await expect(answerCard.locator('.answer-text')).toBeVisible({ timeout: 20_000 })
    await expect(answerCard.getByRole('button', { name: /^Open citation/ }).first()).toBeVisible()

    // One tap: Show on table sends this chat and the answer's items to native AR.
    await answerCard.getByRole('button', { name: 'Show on table' }).click()
    const message = await p.evaluate(() => (window as unknown as { arMessages: { chat_id?: string; item_ids?: string[] }[] }).arMessages.at(-1))
    expect(JSON.stringify(message)).toContain(id2c)
    // Visible in the card: Visualise it opens the drawing, whose own Visualise it is one more tap.
    await expect(answerCard.getByRole('button', { name: 'Visualise it' })).toBeVisible()
    await answerCard.getByRole('button', { name: 'Visualise it' }).click()
    await expect(p.getByRole('dialog', { name: 'Drawing viewer' }).getByRole('region', { name: '3D viewer' })).toBeVisible({ timeout: 10_000 }) // card button opens straight in 3D

    // Phone posts (as AR voice does through the API); the desktop sees it live.
    const voice = 'How many windows are there?'
    const t1 = Date.now()
    const posted = phone.request.post(`${API}/api/chats/${id2c}/messages`, { data: { content: voice, doc_ids: [docId] } })
    await expect(d.locator('.question-bubble').filter({ hasText: voice })).toBeVisible({ timeout: 3000 })
    const voiceMs = Date.now() - t1
    expect((await posted).ok()).toBe(true)
    const voiceCard = d.locator('.exchange:not(.pending-exchange)').filter({ hasText: voice }).last()
    await expect(voiceCard.locator('.answer-text')).toBeVisible({ timeout: 20_000 })
    await testInfo.attach('cross-device-times', { contentType: 'application/json', body: JSON.stringify({ firstEventMs, answerMs, voiceMs, seen }) })
    console.log(JSON.stringify({ firstEventMs, answerMs, voiceMs }))
  } finally { await desktop.close(); await phone.close() }
})

test('a new chat from another device shows a banner; Open follows its live stream; Follow auto-opens', async ({ browser, baseURL }) => {
  const { desktop, phone } = await contexts(browser, baseURL)
  try {
    const p = await phone.newPage(), d = await desktop.newPage()
    await ready(p, '/chat')
    await ready(d, '/chat')
    // Pair the phone with the laptop first (W-39) where the build has it; older builds show the banner to everyone.
    const pairBtn = d.getByRole('button', { name: 'Pair a phone' })
    const paired = (await pairBtn.count()) > 0
    if (paired) {
      await pairBtn.click()
      const link = await d.getByLabel('Pairing link').inputValue()
      await p.goto(link)
      await expect(p.getByRole('combobox', { name: 'Ask about your drawings' })).toBeEnabled({ timeout: 20_000 })
      await p.waitForTimeout(1500)
      await d.keyboard.press('Escape')
    }
    const q1 = "How many doors are there?"
    await d.getByRole('combobox', { name: 'Ask about your drawings' }).fill(q1)
    const t0 = Date.now()
    await d.getByRole('button', { name: 'Send question', exact: true }).click()
    const banner = p.getByTestId('follow-banner')
    // Paired: the chat opens by itself. Unpaired (older build): a banner offers it.
    await expect(banner.or(p.locator('.question-bubble').filter({ hasText: q1 }).first())).toBeVisible({ timeout: 5000 })
    const bannerMs = Date.now() - t0
    if (await banner.count()) {
      await expect(banner).toContainText(q1)
      await banner.getByRole('button', { name: 'Open' }).click()
    }
    await expect(p.locator('.question-bubble').filter({ hasText: q1 }).first()).toBeVisible({ timeout: 10_000 })
    await expect(p.locator('.exchange:not(.pending-exchange) .answer-text').first()).toBeVisible({ timeout: 20_000 })
    await expect(banner).toHaveCount(0)

    if (paired) { console.log(JSON.stringify({ bannerMs, paired })); return }
    // Legacy builds: Follow on (kept in localStorage): the next chat opens by itself.
    await p.evaluate(() => localStorage.setItem('hologram.follow-chats', '1'))
    await p.goto('/#/overview'); await p.reload()
    await expect(p.getByRole('region', { name: 'Workspace overview', exact: true })).toHaveAttribute('data-live', 'open', { timeout: 15_000 })
    const q2 = `How many windows are there? ${Date.now() % 1000}`
    const id2 = await newChat(desktop.request, `Follow ${Date.now()}`)
    await d.goto(`/#/chat?chat=${id2}`)
    await ready(d, `/chat?chat=${id2}`)
    await d.getByRole('combobox', { name: 'Ask about your drawings' }).fill(q2)
    await d.getByRole('button', { name: 'Send question', exact: true }).click()
    await expect(p).toHaveURL(new RegExp(`chat=${id2}`), { timeout: 8000 })
    await expect(p.locator('.question-bubble').filter({ hasText: q2 }).first()).toBeVisible({ timeout: 10_000 })
    console.log(JSON.stringify({ bannerMs }))
  } finally { await desktop.close(); await phone.close() }
})

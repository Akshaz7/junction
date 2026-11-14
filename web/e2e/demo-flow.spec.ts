import { devices, expect, test, type BrowserContext } from '@playwright/test'

// Demo dry run, the exact judge flow with per-step timings:
// laptop asks "How many doors?" on ac20_arc -> opens 2D -> Visualise it (3D); the phone follows the streamed chat
// live, taps Show on table (native AR bridge message = the AR hand-off, with the chat id), and a voice turn posted
// through the API shows up on the laptop. Deployed run:
//   E2E_BASE=https://hologram-khaki.vercel.app E2E_API=https://hologram-khaki.vercel.app npx playwright test e2e/demo-flow.spec.ts
const API = process.env.E2E_API ?? 'http://localhost:8000'
const docId = 'ifc_bench__ac20-arc'
const QUESTION = 'How many doors?'
test.setTimeout(120_000)
if (process.env.E2E_BASE) test.use({ baseURL: process.env.E2E_BASE })

const { defaultBrowserType: _ignored, ...phoneDevice } = devices['iPhone 15 Pro Max']

test('demo flow: laptop asks, 2D, 3D; phone follows live, Show on table; voice turn lands on the laptop', async ({ browser, baseURL }, testInfo) => {
  const desktop = await browser.newContext({ baseURL, viewport: { width: 1400, height: 900 } })
  const phone = await browser.newContext({ ...phoneDevice, baseURL })
  await phone.addInitScript(() => {
    const host = window as unknown as { arMessages: unknown[]; webkit: unknown }
    host.arMessages = []
    host.webkit = { messageHandlers: { ar: { postMessage: (m: unknown) => host.arMessages.push(m) } } }
  })
  const steps: Record<string, number> = {}
  const mark = (name: string, since: number) => { steps[name] = Date.now() - since }
  try {
    const created = await (desktop as BrowserContext).request.post(`${API}/api/chats`, { data: { doc_ids: [docId], title: `Demo flow ${Date.now()}` } })
    expect(created.ok()).toBe(true)
    const id = (await created.json() as { id: string }).id
    const [d, p] = [await desktop.newPage(), await phone.newPage()]
    for (const page of [d, p]) {
      await page.goto(`/#/chat?chat=${id}`)
      await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toBeEnabled({ timeout: 20_000 })
    }
    await p.waitForTimeout(1500) // live socket open

    // 1) Laptop asks.
    await d.getByRole('combobox', { name: 'Ask about your drawings' }).fill(QUESTION)
    const t0 = Date.now()
    await d.getByRole('button', { name: 'Send question', exact: true }).click()
    await expect(p.locator('.pending-exchange .question-bubble, .exchange .question-bubble').filter({ hasText: QUESTION }).first()).toBeVisible({ timeout: 8000 })
    mark('phoneSeesQuestionMs', t0)
    const dCard = d.locator('.exchange:not(.pending-exchange)').filter({ hasText: QUESTION }).last()
    await expect(dCard.locator('.answer-text')).toBeVisible({ timeout: 30_000 })
    mark('laptopAnswerMs', t0)
    const pCard = p.locator('.exchange:not(.pending-exchange)').filter({ hasText: QUESTION }).last()
    await expect(pCard.locator('.answer-text')).toBeVisible({ timeout: 30_000 })
    mark('phoneAnswerMs', t0)
    await expect(pCard.getByRole('button', { name: /^Open citation/ }).first()).toBeVisible()

    // 2) Laptop opens the numbered 2D drawing, then Visualise it (3D).
    const t1 = Date.now()
    await dCard.getByRole('button', { name: /^Open citation/ }).first().click()
    const viewer = d.getByRole('region', { name: 'Drawing viewer' })
    await expect(viewer).toBeVisible({ timeout: 15_000 })
    await expect(viewer.getByRole('button', { name: '2D' })).toHaveAttribute('aria-pressed', 'true', { timeout: 15_000 })
    mark('open2dMs', t1)
    const t2 = Date.now()
    await viewer.locator('.viewer3d-visualise-button').click()
    await expect(viewer.getByRole('region', { name: '3D viewer' })).toBeVisible({ timeout: 30_000 })
    mark('visualise3dMs', t2)

    // 3) Phone: Show on table hands this chat and the answer's items to native AR.
    const t3 = Date.now()
    await pCard.getByRole('button', { name: 'Show on table' }).click()
    const message = await p.evaluate(() => (window as unknown as { arMessages: { doc_id?: string; chat_id?: string; item_ids?: string[] }[] }).arMessages.at(-1))
    expect(message?.chat_id).toBe(id)
    expect(message?.doc_id).toBe(docId)
    expect(message?.item_ids?.length).toBeGreaterThan(0)
    mark('showOnTableMs', t3)

    // 4) Voice turn posted through the API (as the AR app does) appears on the laptop.
    const voice = 'How many windows are there?'
    const t4 = Date.now()
    const posted = phone.request.post(`${API}/api/chats/${id}/messages`, { data: { content: voice, doc_ids: [docId] } })
    await expect(d.locator('.question-bubble').filter({ hasText: voice })).toBeVisible({ timeout: 8000 })
    mark('voiceOnLaptopMs', t4)
    expect((await posted).ok()).toBe(true)
    await expect(d.locator('.exchange:not(.pending-exchange)').filter({ hasText: voice }).locator('.answer-text')).toBeVisible({ timeout: 30_000 })
    mark('voiceAnswerOnLaptopMs', t4)
    await testInfo.attach('demo-flow-times', { contentType: 'application/json', body: JSON.stringify(steps) })
    console.log(JSON.stringify(steps))
  } finally { await desktop.close(); await phone.close() }
})

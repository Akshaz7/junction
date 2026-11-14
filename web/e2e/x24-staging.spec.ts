import { devices, expect, test, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

// X-24: demo dry run on staging. Soft steps: every failure is recorded, screenshotted and the run continues.
// Run: E2E_BASE=https://hologram-staging-pi.vercel.app npx playwright test e2e/x24-staging.spec.ts
// Request budget: at most 55 /api and /ws requests in total (limit is 120/min/IP and prod is in use).
const docId = 'ifc_bench__ac20-arc'
const BACKEND_WS = process.env.E2E_WS ?? 'wss://obviously-present-piglet.eur-1.aiven.app/ws'
const shots = fileURLToPath(new URL('../../results/qa/shots/', import.meta.url))
if (process.env.E2E_BASE) test.use({ baseURL: process.env.E2E_BASE })
test.setTimeout(240_000)
const box = 'Ask about your drawings'

test('X-24 staging demo dry run', async ({ browser, baseURL }) => {
  await mkdir(shots, { recursive: true })
  const desktop = await browser.newContext({ baseURL, viewport: { width: 1440, height: 1000 } })
  const phoneCtx = await browser.newContext({ ...(({ defaultBrowserType: _d, ...r }) => r)(devices['iPhone 15 Pro Max']) })
  const d = await desktop.newPage()
  let requests = 0
  const budget = (page: Page) => page.on('request', (r) => { if (/\/api\/|\/ws/.test(r.url())) requests++ })
  budget(d)
  const problems: string[] = []
  const timings: Record<string, number> = {}
  const shot = (page: Page, name: string) => page.screenshot({ path: `${shots}x24-${name}.png` }).catch(() => undefined)
  async function step(name: string, fn: () => Promise<void>) {
    const t = Date.now()
    try {
      if (requests > 55) throw new Error(`request budget exceeded (${requests})`)
      await fn()
      timings[name] = Date.now() - t
      await shot(d, `${name}-ok`)
    } catch (error) {
      timings[name] = Date.now() - t
      const message = String((error as Error).message).split('\n').slice(0, 3).join(' | ')
      problems.push(`${name}: ${message}`)
      await shot(d, `${name}-FAIL`)
    }
  }
  const frames: string[] = []
  let code = ''
  let phone: Page | undefined
  let chatId = ''

  await step('01-open-ac20', async () => {
    await d.goto('/#/data')
    await expect(d.getByText('Connected workspace', { exact: true })).toBeVisible({ timeout: 30_000 })
    await d.getByRole('searchbox', { name: 'Search documents' }).fill('AC20')
    const row = d.locator(`[data-doc-id="${docId}"]`)
    await expect(row).toBeVisible({ timeout: 20_000 })
    await row.getByRole('button', { name: /^Open / }).click()
    const detail = d.getByRole('complementary', { name: 'Document details' })
    await expect(detail).toBeVisible()
    await detail.getByRole('button', { name: 'Ask about it', exact: true }).last().click()
    await expect(d.getByLabel('Selected documents')).toContainText(/AC20/i)
  })

  await step('02-pair-phone-qr', async () => {
    await d.getByRole('button', { name: 'Pair a phone' }).click()
    const link = await d.getByLabel('Pairing link').inputValue()
    code = new URL(link).hash.match(/code=(\w+)/)![1]
    const { default: qrcode } = await import('qrcode-generator')
    const roundTrip = (markup: string) => d.evaluate((html) => { const n = document.createElement('div'); n.innerHTML = html; return n.innerHTML }, markup)
    const expected = qrcode(0, 'M'); expected.addData(`hologram://pair?code=${code}`); expected.make()
    const svg = await roundTrip(expected.createSvgTag({ cellSize: 4, margin: 2, scalable: true }))
    const actual = await d.locator('.pair-qr').innerHTML()
    const norm = (v: string) => v
    const web = qrcode(0, 'M'); web.addData(link); web.make()
    const webSvg = await roundTrip(web.createSvgTag({ cellSize: 4, margin: 2, scalable: true }))
    problems.push(`INFO QR matches native link: ${norm(actual) === norm(svg)}; matches https link: ${norm(actual) === norm(webSvg)}`)
    await d.screenshot({ path: `${shots}x24-02-pair-popover.png` })
    const text = await d.locator('.pair-popover').innerText().catch(() => '')
    if (/Stoa/i.test(text)) problems.push(`02-pair-phone-qr: popover copy names the competitor product: "${text.split('\n').find((l) => /Stoa/i.test(l))}"`)
    await d.keyboard.press('Escape')
    expect(norm(actual), 'QR encodes hologram://pair?code=<code>').toBe(norm(svg))
  })

  await step('03-phone-ws-open', async () => {
    phone = await phoneCtx.newPage()
    budget(phone)
    await phone.goto('about:blank')
    await phone.exposeFunction('__frame', (f: string) => { frames.push(f) })
    await phone.evaluate((url) => new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(url)
      ;(window as unknown as { __ws: WebSocket }).__ws = ws
      ws.onmessage = (m) => { void (window as unknown as { __frame: (f: string) => void }).__frame(String(m.data)) }
      ws.onopen = () => resolve()
      ws.onerror = () => reject(new Error('ws error ' + url))
      setTimeout(() => reject(new Error('ws timeout')), 10000)
    }), BACKEND_WS)
    await d.waitForTimeout(1000)
  })

  await step('04-ask-doors-and-windows', async () => {
    const composer = d.getByRole('combobox', { name: box })
    await expect(composer).toBeEnabled({ timeout: 20_000 })
    await composer.fill('how many doors and windows')
    const t = Date.now()
    await d.getByRole('button', { name: 'Send question', exact: true }).click()
    const card = d.getByTestId('answer-card').last()
    await expect(card.locator('.answer-text')).toBeVisible({ timeout: 60_000 })
    timings['answer-ms'] = Date.now() - t
    const text = await card.locator('.answer-text').innerText()
    expect(text, 'both counts in one answer').toMatch(/door/i)
    expect(text).toMatch(/window/i)
    chatId = (await d.evaluate(() => window.location.hash.match(/chat=([^&]+)/)?.[1] ?? '')) as string
    problems.push(`INFO answer: ${text.replace(/\s+/g, ' ').slice(0, 160)}`)
  })

  await step('05-open-2d-citation', async () => {
    const card = d.getByTestId('answer-card').last()
    await card.getByRole('button', { name: /^Open citation 1$/ }).first().click()
    const viewer = d.getByRole('region', { name: 'Drawing viewer', exact: true })
    await expect(viewer).toBeVisible()
    await expect(viewer.getByTestId(/^evidence-box-\d+$/).first()).toBeVisible({ timeout: 30_000 })
    problems.push(`INFO evidence boxes in 2D: ${await viewer.getByTestId(/^evidence-box-\d+$/).count()}`)
  })

  await step('06-visualise-it-3d', async () => {
    const card = d.getByTestId('answer-card').last()
    await card.getByRole('button', { name: 'Visualise it' }).click()
    const viewer = d.getByRole('region', { name: 'Drawing viewer', exact: true })
    await expect(viewer.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
    await d.waitForTimeout(2500)
  })

  await step('07-remove-front-door-848-33', async () => {
    const composer = d.getByRole('combobox', { name: box })
    await expect(composer).toBeEnabled()
    await composer.fill('remove the front door')
    await d.getByRole('button', { name: 'Send question', exact: true }).click()
    const card = d.getByTestId('answer-card').last()
    await expect(card.locator('.answer-text')).toContainText(/remov|hid|front/i, { timeout: 60_000 })
    await d.waitForTimeout(1500)
    const body = await d.locator('main').innerText()
    problems.push(`INFO removal answer: ${(await card.locator('.answer-text').innerText()).replace(/\s+/g, ' ').slice(0, 200)}`)
    expect(body, 'a card quoting 848/2017').toMatch(/848\/2017/)
    expect(body, 'section 33').toMatch(/§\s?33|section 33/i)
  })

  await step('08-phone-api-and-ws', async () => {
    expect(chatId, 'chat id in URL').toBeTruthy()
    const want = createHash('sha256').update(`${code}:${chatId}`).digest('hex').slice(0, 16)
    const parsed = frames.map((f) => { try { return JSON.parse(f) as Record<string, unknown> } catch { return {} } })
    const pair = parsed.find((e) => e.type === 'pair.chat' && e.chat_id === chatId)
    expect(pair, 'pair.chat frame for this chat reached the phone WS').toBeTruthy()
    expect(pair?.proof, 'proof matches sha256(code:chat)').toBe(want)
    const scene = parsed.filter((e) => e.type === 'scene.edit' && e.doc_id === docId)
    problems.push(`INFO phone WS frames: ${[...new Set(parsed.map((e) => String(e.type)))].join(', ')}`)
    expect(scene.length, 'scene.edit command frame reached the phone WS').toBeGreaterThan(0)
    const res = await phoneCtx.request.get(`${(baseURL ?? '')}/api/pair/${code}/chats/${chatId}`)
    expect(res.ok()).toBe(true)
    expect(((await res.json()) as { paired?: boolean }).paired, 'phone GET pair check').toBe(true)
  })

  console.log(JSON.stringify({ requests, timings, problems }, null, 1))
  await desktop.close(); await phoneCtx.close()
})

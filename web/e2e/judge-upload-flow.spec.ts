import { devices, expect, test, type Page } from '@playwright/test'
import { mkdir, readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

// Judge rehearsal: upload a random floor plan, ask two questions, pair a phone, Visualise it. Soft steps, screenshots, request count.
// Local: npx playwright test e2e/judge-upload-flow.spec.ts. Prod: E2E_BASE=https://hologram-khaki.vercel.app (keep to 20 requests).
const shots = fileURLToPath(new URL('../../results/qa/shots/', import.meta.url))
const plan = fileURLToPath(new URL('../../data/judges/random/' + (process.env.JUDGE_FILE ?? 'simon_house.jpg'), import.meta.url))
if (process.env.E2E_BASE) test.use({ baseURL: process.env.E2E_BASE })
test.setTimeout(300_000)
const box = 'Ask about your drawings'

test('judge flow: upload, ask, pair, visualise', async ({ browser, baseURL }) => {
  await mkdir(shots, { recursive: true })
  const desktop = await browser.newContext({ baseURL, viewport: { width: 1440, height: 1000 } })
  const phoneCtx = await browser.newContext({ ...(({ defaultBrowserType: _d, ...r }) => r)(devices['iPhone 15 Pro Max']), baseURL })
  const d = await desktop.newPage(), p = await phoneCtx.newPage()
  let requests = 0
  for (const pg of [d, p]) pg.on('request', (r) => { if (/\/api\/|\/ws/.test(r.url())) requests++ })
  const log: string[] = [], result: Record<string, string> = {}
  let docId = ''
  async function step(name: string, fn: () => Promise<void>) {
    const t = Date.now()
    try { await fn(); result[name] = `PASS ${Date.now() - t} ms`; await d.screenshot({ path: `${shots}judge-${name}-ok.png` }) }
    catch (e) { result[name] = `FAIL ${Date.now() - t} ms: ${String((e as Error).message).split('\n').slice(0, 3).join(' | ').slice(0, 300)}`; await d.screenshot({ path: `${shots}judge-${name}-FAIL.png` }).catch(() => {}) }
  }
  const answerOf = async (n: number) => (await d.getByTestId('answer-card').nth(n).locator('.answer-text').innerText()).replace(/\s+/g, ' ')

  await step('1-upload', async () => {
    await d.goto('/#/data')
    await d.getByRole('button', { name: 'Upload', exact: true }).first().click()
    const sent = d.waitForResponse((r) => r.url().endsWith('/api/upload') && r.request().method() === 'POST')
    await d.getByLabel('Choose a drawing', { exact: true }).setInputFiles({ name: `judge-${Date.now()}.jpg`, mimeType: 'image/jpeg', buffer: await readFile(plan) })
    const response = await sent
    expect(response.ok(), `upload HTTP ${response.status()}`).toBe(true)
    docId = ((await response.json()) as { doc_id?: string; id?: string }).doc_id ?? ''
    const dialog = d.locator('dialog.upload-dialog')
    await expect(dialog.getByRole('button', { name: /Ready/ })).toBeVisible({ timeout: 120_000 })
    await d.screenshot({ path: `${shots}judge-1-ready.png` })
    await dialog.getByRole('button', { name: 'Open', exact: true }).click()
    await d.getByRole('complementary', { name: 'Document details' }).getByRole('button', { name: 'Ask about it', exact: true }).last().click()
    await expect(d.getByLabel('Selected documents')).toBeVisible()
  })
  // Finding to report: the dialog says Ready once the pages are readable, but the plan map is still being built.
  await step('1b-fully-processed', async () => {
    const t0 = Date.now()
    for (;;) {
      const status = ((await (await d.request.get(`/api/docs/${docId}/ingest`)).json()) as { status?: string }).status
      if (status === 'ready' || status === 'partial') { log.push(`ingest ${status} after ${Math.round((Date.now() - t0) / 1000)} s more`); break }
      if (status === 'failed' || Date.now() - t0 > 120_000) throw new Error(`ingest ${status}`)
      await d.waitForTimeout(4000)
    }
  })
  await step('2a-total-floor-area', async () => {
    const c = d.getByRole('combobox', { name: box })
    await expect(c).toBeEnabled({ timeout: 20_000 })
    await c.fill("what's the total floor area")
    await d.getByRole('button', { name: 'Send question', exact: true }).click()
    await expect(d.getByTestId('answer-card').nth(0).locator('.answer-text')).toBeVisible({ timeout: 90_000 })
    log.push(`area answer: ${(await answerOf(0)).slice(0, 220)}`)
  })
  await step('2b-doors-and-windows', async () => {
    const c = d.getByRole('combobox', { name: box })
    await expect(c).toBeEnabled({ timeout: 20_000 })
    await c.fill('how many doors and windows')
    await d.getByRole('button', { name: 'Send question', exact: true }).click()
    await expect(d.getByTestId('answer-card').nth(1).locator('.answer-text')).toBeVisible({ timeout: 90_000 })
    const text = await answerOf(1)
    log.push(`doors/windows answer: ${text.slice(0, 220)}`)
    expect(text).toMatch(/door/i); expect(text).toMatch(/window/i)
  })
  const chatId = await d.evaluate(() => window.location.hash.match(/chat=([^&]+)/)?.[1] ?? '')
  await step('3-pair-phone-follows', async () => {
    await d.getByRole('button', { name: 'Pair a phone' }).click()
    const link = await d.getByLabel('Pairing link').inputValue()
    await p.goto(link)
    await expect(p).toHaveURL(new RegExp(`chat=${chatId}`), { timeout: 20_000 })
    await expect(p.locator('.question-bubble').first()).toBeVisible({ timeout: 20_000 })
    await p.screenshot({ path: `${shots}judge-3-phone.png` })
    await d.keyboard.press('Escape')
  })
  await step('4-visualise-3d', async () => {
    const card = d.getByTestId('answer-card').last()
    await card.getByRole('button', { name: 'Visualise it' }).click()
    const v = d.getByRole('region', { name: 'Drawing viewer', exact: true })
    await expect(v.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 90_000 })
    await d.waitForTimeout(2500)
    if (docId) {
      const scene = await d.request.get(`/api/docs/${docId}/scene`)
      const manifest = await scene.json() as { items?: Record<string, unknown>[] | Record<string, Record<string, unknown>> }
      const items = Array.isArray(manifest.items) ? manifest.items : Object.values(manifest.items ?? {})
      const kinds: Record<string, number> = {}
      for (const i of items) kinds[String(i.kind ?? 'other')] = (kinds[String(i.kind ?? 'other')] ?? 0) + 1
      log.push(`scene items by kind: ${JSON.stringify(kinds)}`)
      expect(kinds.wall ?? 0, 'walls in the scene').toBeGreaterThan(0)
    }
  })
  console.log(JSON.stringify({ requests, result, log }, null, 1))
  await desktop.close(); await phoneCtx.close()
  expect(Object.values(result).every((v) => v.startsWith('PASS')), JSON.stringify(result)).toBe(true)
})

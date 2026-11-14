import { test as base, expect, type Page, type APIRequestContext } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Answer, Document } from '../src/lib/types'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'

export const production = !/^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/.test(process.env.E2E_BASE ?? 'http://localhost:5173')
export const repoRoot = fileURLToPath(new URL('../../', import.meta.url))
export const fixtureManifest = JSON.parse(readFileSync(resolve(repoRoot, 'results/final/E2E/fixtures.json'), 'utf8')) as Record<string, [string, number]>
export const test = base.extend<{ monitor: void }>({
  monitor: [async ({ page, context }, use, info) => {
    const errors: string[] = [], http: { method: string; path: string; status: number }[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    page.on('response', (r) => {
      if (r.url().includes('/api/')) http.push({ method: r.request().method(), path: new URL(r.url()).pathname, status: r.status() })
    })
    // Production is strictly read-only: even an accidental UI click cannot upload, edit, run checks or create a chat.
    if (production) await context.route('**/api/**', async (route) => {
      if (!['GET', 'HEAD', 'OPTIONS'].includes(route.request().method())) {
        errors.push(`Blocked production mutation: ${route.request().method()} ${new URL(route.request().url()).pathname}`)
        await route.abort('blockedbyclient')
      } else await route.continue()
    })
    await use()
    await info.attach('network-and-browser.json', { body: JSON.stringify({ errors, http }, null, 2), contentType: 'application/json' })
    if (info.status === info.expectedStatus) expect(errors, 'No browser crashes or production writes').toEqual([])
  }, { auto: true }],
})
export { expect }

export async function docs(request: APIRequestContext): Promise<Document[]> {
  const response = await request.get('/api/docs')
  expect(response.ok(), `Document catalogue HTTP ${response.status()}`).toBe(true)
  const data = await response.json()
  const rows = data.sources.flatMap((s: { docs: Document[] }) => s.docs) as Document[]
  return rows.filter((d) => d.source !== 'uploads')
}

export async function chooseDocument(request: APIRequestContext, kind: string) {
  const rows = (await docs(request)).filter((d) => d.kind === kind)
  expect(rows.length, `Real ${kind} documents must exist`).toBeGreaterThan(0)
  // Choose by available evidence, never by a document id, room, count or coordinate.
  for (const doc of rows.slice(0, 15)) {
    const response = await request.get(`/api/docs/${encodeURIComponent(doc.doc_id)}/planmap/1`)
    if (response.ok() && ((await response.json()).items ?? []).some((i: { kind: string }) => i.kind === 'door' || i.kind === 'window')) return doc
  }
  throw new Error(`No ${kind} document with door/window evidence among the first ${Math.min(rows.length, 15)} candidates`)
}

export async function openDocument(page: Page, doc: Document) {
  await page.goto('/?viewer3dTest=1#/data')
  const search = page.getByRole('searchbox', { name: 'Search documents' })
  await search.fill(doc.doc_id)
  const selected = page.locator(`[data-doc-id="${doc.doc_id}"]`)
  await selected.locator('.data-open-file').click()
  const detail = page.getByRole('complementary', { name: 'Document details', exact: true })
  await expect(detail).toBeVisible()
  await expect(selected).toHaveAttribute('data-selected', 'true')
  return { detail, selected, search }
}

export async function chatFor(page: Page, doc: Document) {
  const { detail } = await openDocument(page, doc)
  await detail.getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  await expect(page.getByLabel('Selected documents')).toContainText(doc.title)
}

export async function observeLoading(page: Page) {
  await page.evaluate(() => {
    const state = { skeleton: false, status: [] as string[] }
    Object.assign(window, { __finalLoading: state })
    const sample = () => {
      if (document.querySelector('[data-testid="answer-skeleton"]')) state.skeleton = true
      for (const node of document.querySelectorAll('.pending-exchange .thinking-text')) {
        const text = node.getAttribute('aria-label') ?? node.textContent ?? ''
        if (text && !state.status.includes(text)) state.status.push(text)
      }
    }
    new MutationObserver(sample).observe(document.body, { subtree: true, childList: true, attributes: true })
  })
}

export async function ask(page: Page, question: string): Promise<Answer> {
  if (production) throw new Error('Production questions disabled: reuse saved answers; zero question budget used')
  await observeLoading(page)
  const count = await page.getByTestId('answer-card').count()
  const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
  await expect(composer).toBeEnabled()
  await composer.fill(question)
  const sent = page.waitForResponse((r) => /\/api\/chats\/[^/]+\/messages$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Send question', exact: true }).click()
  const response = await sent
  expect(response.ok(), `Question HTTP ${response.status()}`).toBe(true)
  expect(response.headers()['content-type']).toContain('text/event-stream')
  const stream = await response.text()
  const answers = stream.replace(/\r\n/g, '\n').split('\n\n').flatMap((block) => {
    if (!/^event:\s*answer$/m.test(block)) return []
    return [JSON.parse(block.split('\n').filter((s) => s.startsWith('data:')).map((s) => s.slice(5).trim()).join('\n')) as Answer]
  })
  expect(answers, 'Exactly one completed answer in the live stream').toHaveLength(1)
  expect(stream).not.toMatch(/"stub"\s*:\s*true/)
  const answer = answers[0]
  await test.info().attach('answer.json', { body: JSON.stringify(answer, null, 2), contentType: 'application/json' })
  await expect(page.getByTestId('answer-card')).toHaveCount(count + 1)
  await expect(page.getByTestId('answer-card').last().locator('.answer-text')).toBeVisible()
  const loading = await page.evaluate(() => (window as unknown as { __finalLoading: { skeleton: boolean; status: string[] } }).__finalLoading)
  expect.soft(loading.skeleton, 'Skeleton appears during the real request').toBe(true)
  expect.soft(loading.status.length, 'Live status appears during the real request').toBeGreaterThan(0)
  await test.info().attach('loading.json', { body: JSON.stringify(loading), contentType: 'application/json' })
  return answer
}

export async function savedAnswer(page: Page, request: APIRequestContext) {
  const response = await request.get('/api/chats')
  expect(response.ok()).toBe(true)
  const data = await response.json()
  const chats = Array.isArray(data) ? data : data.chats
  for (const chat of chats.slice(0, 40)) {
    const detail = await request.get(`/api/chats/${chat.id}`)
    if (!detail.ok()) continue
    const messages = (await detail.json()).messages ?? []
    const answer = messages.map((m: { answer?: Answer }) => m.answer).find((a?: Answer) => a?.citations?.length && a?.reasoning?.steps?.length && !a.answer.abstained)
    if (!answer) continue
    await page.goto(`/?viewer3dTest=1#/chat?chat=${encodeURIComponent(chat.id)}`)
    await expect(page.getByTestId('answer-card').filter({ hasText: answer.question }).first()).toBeVisible()
    return answer as Answer
  }
  throw new Error('No saved, cited answer with reasoning found in the first 40 chats; cannot verify production without writing')
}

export async function viewerState(page: Page) {
  return page.locator('.viewer3d:visible canvas').evaluate((node) => {
    const handle = (node as LinkedViewerCanvas).__viewer3d
    if (!handle) throw new Error('Viewer test handle missing')
    return { highlights: handle.state().highlighted, commands: handle.commandState(), camera: handle.camera() }
  })
}

import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { expect, test, type Locator, type Page } from '@playwright/test'
import type { Answer, Document } from '../src/lib/types'
import type { LinkedViewerCanvas } from '../src/viewer3d/Viewer3D'
import type { SceneCommand } from '../src/viewer3d/commands'

export const api = 'http://localhost:8000'
export const ac20 = 'ifc_bench__ac20-arc'
export const countQuestion = 'How many windows are shown on this floor plan?'
const screenshots = fileURLToPath(new URL('../../results/e2e/', import.meta.url))
type LiveAnswer = Answer & { evidence: { scene: { commands?: SceneCommand[] } } }
type StatusHost = Window & { __demoStatus?: { texts: string[]; observer: MutationObserver } }

export async function shot(page: Page, step: string) {
  await mkdir(screenshots, { recursive: true })
  await page.screenshot({ path: `${screenshots}/${step}.png`, fullPage: true })
}

export async function rasterPick(page: Page) {
  const primary = 'cubicasa5k__high-quality-108'
  const response = await page.request.get(`${api}/api/docs/${primary}`)
  if (response.status() !== 404) {
    expect(response.ok(), 'C01 must be reachable on the real API').toBe(true)
    return { doc: await response.json() as Document, gold: 7, candidate: 'C01' }
  }
  // C28 is allowed only when C01 is absent, never to mask a wrong answer.
  const fallback = await page.request.get(`${api}/api/docs/cubicasa5k__colorful-7513`)
  expect(fallback.ok(), 'Seed C01 or its documented C28 fallback').toBe(true)
  test.info().annotations.push({ type: 'demo-pick', description: 'C01 absent (404); using documented C28, gold 5.' })
  return { doc: await fallback.json() as Document, gold: 5, candidate: 'C28' }
}

export async function selectFromData(page: Page, doc: Document, phone: boolean) {
  const navigation = page.getByRole('navigation', { name: phone ? 'Mobile navigation' : 'Workspace navigation', exact: true })
  await navigation.getByRole('link', { name: 'Data', exact: true }).click()
  await page.getByRole('searchbox', { name: 'Search documents' }).fill(doc.doc_id)
  await page.locator(`[data-doc-id="${doc.doc_id}"] .data-open-file`).click()
  const details = page.getByRole('complementary', { name: 'Document details' })
  await expect(details).toBeVisible()
  // Both responsive actions select this document; use the first exposed action.
  await details.getByRole('button', { name: 'Ask about it', exact: true }).first().click()
  await expect(page).toHaveURL(/#\/chat(?:\?|$)/)
  await expect(page.getByLabel('Selected documents')).toContainText(doc.title)
}

function assertNoStub(value: unknown) {
  if (value === null || typeof value !== 'object') return
  for (const [key, child] of Object.entries(value)) {
    if (key === 'stub') expect(child, 'Real SSE must never contain stub: true').not.toBe(true)
    assertNoStub(child)
  }
}

/** Observe rendered statuses without delaying, intercepting or replacing any request. */
async function observeStatuses(page: Page) {
  await page.evaluate(() => {
    const host = window as StatusHost
    host.__demoStatus?.observer.disconnect()
    const texts: string[] = []
    const observer = new MutationObserver(() => {
      for (const node of document.querySelectorAll<HTMLElement>('.pending-exchange .thinking-text')) {
        const text = node.getAttribute('aria-label')
        if (text && node.getClientRects().length && getComputedStyle(node).visibility !== 'hidden' && texts.at(-1) !== text) texts.push(text)
      }
    })
    observer.observe(document.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-label'] })
    host.__demoStatus = { texts, observer }
  })
}

export async function ask(page: Page, question: string, docId: string, requireStatuses = false) {
  return test.step(`Ask live: ${question}`, async () => {
    const composer = page.getByRole('combobox', { name: 'Ask about your drawings' })
    await composer.fill(question)
    await observeStatuses(page)
    const responsePromise = page.waitForResponse((response) => response.request().method() === 'POST'
      && /\/api\/chats\/[^/]+\/messages$/.test(new URL(response.url()).pathname), { timeout: 60_000 })
    await page.getByRole('button', { name: 'Send question', exact: true }).click()
    const response = await responsePromise
    expect(response.ok(), 'The actual browser message POST must succeed').toBe(true)
    expect(response.headers()['content-type']).toContain('text/event-stream')
    expect(response.request().postDataJSON()).toEqual({ content: question, doc_ids: [docId] })
    const stream = await response.text()
    expect(stream, 'Scan the entire captured stream, including trace events').not.toMatch(/"stub"\s*:\s*true/)
    const events = stream.replace(/\r\n/g, '\n').split('\n\n').flatMap((block) => {
      const lines = block.split('\n')
      const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
      const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
      if (!event || !data) return []
      const parsed: unknown = JSON.parse(data)
      assertNoStub(parsed)
      return [{ event, data: parsed }]
    })
    const answers = events.filter((event) => event.event === 'answer')
    expect(answers, 'Exactly one final answer in the real SSE').toHaveLength(1)
    const answer = answers[0].data as LiveAnswer
    expect(answer.answer.abstained).toBe(false)
    expect(answer.question).toBe(question)
    expect(answer.doc_ids).toEqual([docId])
    expect(answer.evidence.scene.doc_id).toBe(docId)
    expect(answer.trace.length).toBeGreaterThan(0)
    const statuses = await page.evaluate(() => (window as StatusHost).__demoStatus?.texts ?? [])
    await test.info().attach(`SSE ${question}`, { body: stream, contentType: 'text/event-stream' })
    await test.info().attach(`Rendered statuses ${question}`, { body: JSON.stringify(statuses), contentType: 'application/json' })
    if (requireStatuses) {
      expect(statuses, 'Thinking must actually render, even for a fast count').toContain('Thinking…')
      const apiStatuses = events.filter((event) => event.event === 'status').map((event) => (event.data as { text: string }).text)
      expect(apiStatuses.length, 'Backend must stream at least one status').toBeGreaterThan(0)
      expect(statuses.some((text) => text !== 'Thinking…' && apiStatuses.includes(text)),
        'At least one real backend status must appear in the UI').toBe(true)
    }
    const card = page.locator('.exchange').filter({ has: page.getByText(question, { exact: true }) }).last()
    await expect(card.locator('.answer-text')).toBeVisible()
    await expect(card.getByTestId('answer-cost')).toBeVisible()
    await expect(page.locator('.pending-exchange')).toHaveCount(0)
    return { answer, card }
  }, { timeout: 60_000 })
}

export async function openDrawing(page: Page, card: Locator, answer: Answer, phone: boolean) {
  await card.locator('.answer-text').getByRole('button', { name: `Open citation ${answer.citations[0].n}`, exact: true }).click()
  const drawing = page.getByRole(phone ? 'dialog' : 'region', { name: 'Drawing viewer', exact: true })
  await expect(drawing).toBeVisible()
  if (phone) await expect(drawing).toHaveAttribute('aria-modal', 'true')
  const image = drawing.getByRole('img', { name: /Drawing:/ })
  await expect(image).toBeVisible({ timeout: 15_000 })
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.complete && node.naturalWidth > 0)).toBe(true)
  const boxes = drawing.locator('.evidence-region')
  const evidence = answer.evidence.boxes.filter((box) => box.page === answer.citations[0].page)
  await expect(boxes).toHaveCount(evidence.length)
  expect(evidence.length).toBeGreaterThan(0)
  expect(await boxes.evaluateAll((nodes) => nodes.map((node) => ({
    id: node.getAttribute('data-item-id'), label: node.querySelector('text')?.textContent,
  })))).toEqual(evidence.map((box) => ({ id: box.item_id, label: box.label })))
  await expect(drawing.getByTestId('drawing-credit')).toBeVisible()
  return drawing
}

export async function viewerState(panel: Locator) {
  return panel.locator('canvas').evaluate((canvas: LinkedViewerCanvas) => {
    if (!canvas.__viewer3d) throw new Error('Opt-in __viewer3d handle is not ready')
    return { highlight: canvas.__viewer3d.state(), commands: canvas.__viewer3d.commandState() }
  })
}

export async function visualise(page: Page, drawing: Locator, answer: Answer) {
  await drawing.getByRole('button', { name: 'Visualise it', exact: true }).click()
  const panel = page.getByRole('dialog', { name: 'Visualise it', exact: true })
  await expect(panel.getByRole('region', { name: '3D viewer', exact: true })).toHaveAttribute('data-state', 'ready', { timeout: 60_000 })
  await expect(panel.getByText('3D view ready', { exact: true })).toBeVisible({ timeout: 60_000 })
  const expected = [...answer.evidence.scene.highlight_item_ids].sort()
  expect(expected.length).toBeGreaterThan(0)
  await expect.poll(async () => (await viewerState(panel)).highlight.highlighted.sort(), { timeout: 15_000 }).toEqual(expected)
  const state = await viewerState(panel)
  for (const box of answer.evidence.boxes) {
    expect(state.highlight.labels[box.item_id]).toBe(box.label)
    await expect(panel.getByLabel(`Item ${box.label}: ${box.item_id}`, { exact: true })).toHaveText(box.label)
  }
  return panel
}

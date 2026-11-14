import { test, expect, type APIRequestContext } from '@playwright/test'
import { readFileSync, writeFileSync } from 'node:fs'
import { basename, resolve } from 'node:path'
import { chooseDocument, fixtureManifest, production, repoRoot } from './final-helpers'
import type { Answer } from '../src/lib/types'

// API-only fallback: this does not claim to verify browser behavior when macOS denies Chromium launch.
test.beforeEach(() => test.skip(process.env.E2E_API !== '1', 'Run explicitly with E2E_API=1; browser specs are the primary done test'))
test.setTimeout(360_000)
let spent = 0

function record(name: string, value: unknown) {
  writeFileSync(test.info().outputPath(name), JSON.stringify(value, null, 2) + '\n')
}

async function answer(request: APIRequestContext, docId: string, question: string) {
  expect(spent, 'F-E2E live spend remains below $3').toBeLessThan(3)
  const created = await request.post('/api/chats', { data: { doc_ids: [docId] } })
  expect(created.ok()).toBe(true)
  const chat = await created.json()
  const response = await request.post(`/api/chats/${chat.id}/messages`, { data: { content: question, doc_ids: [docId] }, timeout: 150_000 })
  expect(response.ok(), `Message HTTP ${response.status()}`).toBe(true)
  expect(response.headers()['content-type']).toContain('text/event-stream')
  const stream = await response.text()
  const events = stream.replace(/\r\n/g, '\n').split('\n\n').flatMap((block) => {
    const event = block.match(/^event:\s*(.+)$/m)?.[1]
    const data = block.split('\n').filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
    return event && data ? [{ event, data: JSON.parse(data) }] : []
  })
  record('stream-events.json', events)
  const answers = events.filter((e) => e.event === 'answer')
  expect(answers, 'The request must finish with one answer').toHaveLength(1)
  const result = answers[0].data as Answer
  spent += result.cost?.usd_total ?? 0
  record('answer-and-budget.json', { doc_id: docId, chat_id: chat.id, answer: result, row_spend_usd: spent })
  expect(stream).not.toMatch(/"stub"\s*:\s*true/)
  expect(events.some((e) => e.event === 'status' || e.event === 'trace'), 'Live status/trace precedes answer').toBe(true)
  expect(result.doc_ids).toContain(docId)
  expect(result.answer.text_md.trim()).not.toBe('')
  expect.soft(result.answer.abstained, 'The uploaded source can answer or explain missing evidence').toBe(false)
  expect.soft(result.reasoning?.steps?.length, 'Answer has How we know steps').toBeGreaterThan(0)
  expect.soft(result.reasoning?.confidence?.label).toMatch(/^(Verified|Cross-checked|Estimate)$/)
  expect.soft(result.reasoning?.confidence?.pct).toBeGreaterThanOrEqual(0)
  expect.soft(result.reasoning?.confidence?.pct).toBeLessThanOrEqual(100)
  expect.soft(result.citations.length, 'Answer cites verifiable source evidence').toBeGreaterThan(0)
  return result
}

test('[SERVER] Read-only local/production endpoints and saved evidence are reachable', async ({ request }) => {
  const responses: Record<string, unknown> = {}
  for (const path of ['/api/health', '/api/docs', '/api/changes', '/api/findings', '/api/chats']) {
    const response = await request.get(path)
    expect.soft(response.ok(), `${path}: HTTP ${response.status()}`).toBe(true)
    const data = await response.json()
    responses[path] = path === '/api/docs' ? { total: data.total, source_count: data.sources?.length } : data
  }
  record('read-only-endpoints.json', responses)
})

for (const kind of ['dxf', 'ifc', 'raster']) {
  test(`[ENGINE] Real ${kind} source yields a streamed answer with citations and reasoning`, async ({ request }) => {
    test.skip(production, 'No messages or chats are created on production')
    const doc = await chooseDocument(request, kind)
    const result = await answer(request, doc.doc_id, 'How many doors are there?')
    record('origin.json', { doc_id: doc.doc_id, source: doc.source, kind })
    expect.soft(result.answer.text_md).toMatch(/\*\*[^*]+\*\*/)
    const pm = await request.get(`/api/docs/${doc.doc_id}/planmap/1`)
    expect(pm.ok()).toBe(true)
    const itemIds = new Set((await pm.json()).items.map((i: { item_id: string }) => i.item_id))
    for (const box of result.evidence.boxes) expect.soft(itemIds.has(box.item_id), `Cited item ${box.item_id} occurs in source`).toBe(true)
  })
}

for (const extension of ['.png', '.jpg', '.dxf', '.ifc']) {
  test(`[SERVER] API fallback upload ${extension}: real ingestion and first question${extension === '.ifc' ? ' on reserved unseen IFC' : ''}`, async ({ request }) => {
    test.skip(production, 'Production is read-only: no uploads')
    const [relative, bytes] = fixtureManifest[extension]
    const upload = await request.post('/api/upload', { multipart: { file: {
      name: `e2e-${Date.now()}-${basename(relative)}`, mimeType: extension === '.png' ? 'image/png' : extension === '.jpg' ? 'image/jpeg' : 'application/octet-stream',
      buffer: readFileSync(resolve(repoRoot, relative)),
    } } })
    expect(upload.ok(), `Upload HTTP ${upload.status()}`).toBe(true)
    const receipt = await upload.json()
    let state: Record<string, unknown> = {}
    await expect.poll(async () => {
      const res = await request.get(`/api/docs/${receipt.doc_id}/ingest`)
      expect(res.ok()).toBe(true)
      state = await res.json()
      return state.status
    }, { timeout: 285_000, intervals: [1000, 2000, 5000] }).not.toBe('running')
    spent += Number(state.cost_usd ?? 0)
    record('ingest.json', { fixture: relative, fixture_bytes: bytes, receipt, state, row_spend_usd: spent })
    expect(state.status, JSON.stringify(state)).toMatch(/^(ready|partial)$/)
    const metadata = await request.get(`/api/docs/${receipt.doc_id}`)
    expect(metadata.ok()).toBe(true)
    const image = await request.get(`/api/docs/${receipt.doc_id}/pages/1/image`)
    expect.soft(image.ok(), 'Uploaded document has a viewable first page').toBe(true)
    const result = await answer(request, receipt.doc_id, 'How many doors are there?')
    expect.soft(result.evidence.boxes.length || result.evidence.scene.highlight_item_ids.length, 'Count evidence identifies boxes or model elements').toBeGreaterThan(0)
  })
}

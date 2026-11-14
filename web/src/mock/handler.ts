import type { Answer, Bbox, Document } from '../lib/types'

export const demoDocument: Document = {
  doc_id: 'demo__garden-room',
  source: 'demo',
  formats: ['svg'],
  kind: 'svg',
  title: 'Garden room — generated for demo',
  pages: 1,
  licence: 'MIT',
  credit: 'Hologram team · generated for demo',
  heldout: false,
}

// Synthetic fixture, never a claim about a dataset drawing or benchmark.
const windows = [
  { item_id: 'window-001', bbox_px: [100, 40, 180, 52] as Bbox },
  { item_id: 'window-002', bbox_px: [260, 40, 340, 52] as Bbox },
]

export function makeDemoAnswer(question: string, docIds: string[] = [demoDocument.doc_id]): Answer {
  const supported = docIds.length === 1 && docIds[0] === demoDocument.doc_id &&
    /\bhow many windows\b|\bcount (?:the )?windows\b/i.test(question.trim())
  const itemIds = supported ? windows.map((window) => window.item_id) : []
  return {
    answer_id: 'demo-answer', question, doc_ids: docIds,
    answer: {
      text_md: supported
        ? `**${windows.length} windows** are recorded in this sample plan (generated for demo). [1]`
        : 'The demo documents do not hold an answer to this question. Try “How many windows are in the sample plan?”',
      value: supported ? windows.length : null,
      unit: supported ? 'count' : null,
      confidence: supported ? 1 : 0,
      abstained: !supported,
    },
    citations: supported ? [{ n: 1, doc_id: demoDocument.doc_id, page: 1, kind: 'region', bbox_px: null, item_ids: itemIds, quote: null }] : [],
    evidence: {
      boxes: supported ? windows.map((window, index) => ({ ...window, page: 1, label: String(index + 1) })) : [],
      scene: { doc_id: docIds[0] ?? '', highlight_item_ids: itemIds, camera_target_item_id: null },
    },
    trace: [{ step: 'route', detail: supported ? 'Count windows in the local fixture (generated for demo).' : 'No matching answer in the local fixture.', ms: 0, model: null, cost_usd: 0 }],
    route: 'planmap', cost: { usd_total: 0, calls: [] }, latency_ms: 0,
  }
}

/** Only these temporary endpoints are mocked; all other routes reach the backend. */
export async function handleMockRequest(request: Request): Promise<Response | null> {
  const { pathname } = new URL(request.url)
  if (request.method === 'GET' && pathname === '/api/docs') return Response.json({
    total: 1, sources: [{ source: demoDocument.source, count: 1, docs: [demoDocument] }],
  })
  if (request.method === 'POST' && pathname === '/api/chats') return Response.json({ id: 'demo', title: 'Offline demo' })
  if (request.method !== 'POST' || !/^\/api\/chats\/[^/]+\/messages$/.test(pathname)) return null
  const body = await request.json() as { content?: unknown; doc_ids?: unknown }
  if (typeof body.content !== 'string' || !body.content.trim() ||
      (body.doc_ids !== undefined && (!Array.isArray(body.doc_ids) || !body.doc_ids.every((id) => typeof id === 'string')))) {
    return Response.json({ detail: 'Message content and optional doc_ids array are required.' }, { status: 400 })
  }
  const answer = makeDemoAnswer(body.content, body.doc_ids as string[] | undefined)
  const events = [
    ['status', { text: 'Thinking…' }],
    ['status', { text: `Exploring document: ${demoDocument.title}` }],
    ['trace', answer.trace[0]],
    ['answer', answer],
  ]
  return new Response(events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join(''), {
    headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
  })
}

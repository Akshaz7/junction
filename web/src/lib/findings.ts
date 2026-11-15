import { workspaceApi } from './api'
import type { Answer, Bbox, Citation, Document, PlanMap } from './types'
import { sourcedCards, type AdvisorCard } from '../viewer3d/advisor'

export type { AdvisorCard }
export interface Finding {
  id: string; doc_id: string; rule_id: string; item_ids: string[]
  severity: 'violation' | 'suggestion' | 'info'; message: string; detail: Record<string, unknown>
  rule: { id: string; text: string; source_title?: string; section?: string; url?: string; quote?: string; translation?: string }
}

export const severityLabels = { violation: 'Violations', suggestion: 'Suggestions', info: 'Information' } as const
export function groupFindings(findings: Finding[]) {
  return (['violation', 'suggestion', 'info'] as const).map((severity) => ({ severity, label: severityLabels[severity], findings: findings.filter((finding) => finding.severity === severity) }))
}

export class FindingsApi {
  constructor(private transport: typeof fetch = (...args) => fetch(...args)) {}
  private async request<T>(path: string, signal?: AbortSignal, body?: unknown): Promise<T> {
    const response = await this.transport(path, { signal, ...(body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
    if (!response.ok) throw new Error(`Could not ${body === undefined ? 'load' : 'run'} checks (${response.status}). Please try again.`)
    return response.json() as Promise<T>
  }
  async list(docId: string, signal?: AbortSignal) { return (await this.request<{ findings: Finding[] }>(`/api/findings?doc_id=${encodeURIComponent(docId)}`, signal)).findings }
  run(docId: string, signal?: AbortSignal) { return this.request<{ status: string; detail?: string; findings: Finding[]; coverage?: { checked: string[]; not_checked: { rule_id: string; reason: string }[] } | null }>('/api/findings/run', signal, { doc_id: docId }) }
  async advise(docId: string, signal?: AbortSignal) { return sourcedCards(await this.request('/api/advise', signal, { doc_id: docId })) }
}
export const findingsApi = new FindingsApi()

/** Adapt sourced items to the same answer/citation inputs used by the chat drawing viewer. */
export function itemEvidence(docId: string, itemIds: string[], text: string, maps: PlanMap[]): { answer: Answer; citation: Citation } {
  const ids = [...new Set(itemIds)]
  const boxes: Answer['evidence']['boxes'] = []
  for (const map of maps) for (const item of map.items) {
    if (ids.includes(item.item_id) && item.bbox_px && item.bbox_px.every(Number.isFinite)) boxes.push({ item_id: item.item_id, page: map.page, bbox_px: item.bbox_px as Bbox, label: String(ids.indexOf(item.item_id) + 1) })
  }
  const page = boxes[0]?.page ?? 1
  const citation: Citation = { n: 1, doc_id: docId, page, kind: 'element', bbox_px: null, item_ids: ids, quote: text }
  const citations = [...new Set([page, ...boxes.map((box) => box.page)])].map((p, index) => ({ ...citation, n: index + 1, page: p }))
  return { citation, answer: {
    answer_id: '', question: '', doc_ids: [docId],
    answer: { text_md: text, value: null, unit: null, confidence: 0, abstained: false },
    citations, evidence: { boxes, scene: { doc_id: docId, highlight_item_ids: ids, camera_target_item_id: ids[0] ?? null } },
    trace: [], route: 'index', cost: { usd_total: 0, calls: [] }, latency_ms: 0,
  } }
}

export async function openFindingEvidence(doc: Document, itemIds: string[], text: string, signal: AbortSignal) {
  const maps = await Promise.allSettled(Array.from({ length: doc.pages }, (_, index) => workspaceApi.getPlanMap(doc.doc_id, index + 1, signal)))
  signal.throwIfAborted()
  // IFC elements without page coordinates still open in 3D with the exact source item IDs.
  return itemEvidence(doc.doc_id, itemIds, text, maps.flatMap((result) => result.status === 'fulfilled' ? [result.value] : []))
}

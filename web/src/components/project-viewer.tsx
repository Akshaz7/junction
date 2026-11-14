import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { DocumentViewer, useViewerSheet } from './document-viewer'
import { workspaceApi } from '../lib/api'
import type { Answer, Citation } from '../lib/types'

export type ViewerTarget = { answer: Answer; citation: Citation; mode: '2d' | '3d'; request: number }

/** Same answer object the chat builds for a citation, so the viewer highlights items exactly the same way. */
export async function buildViewerTarget(docId: string, itemIds: string[], signal?: AbortSignal): Promise<Omit<ViewerTarget, 'request'>> {
  const doc = await workspaceApi.getDocument(docId)
  let boxes: Answer['evidence']['boxes'] = []
  let page = 1
  if (itemIds.length) {
    const wanted = new Set(itemIds)
    const maps = await Promise.allSettled(Array.from({ length: Math.max(1, doc.pages) }, (_, index) => workspaceApi.getPlanMap(docId, index + 1, signal)))
    for (const result of maps) {
      if (result.status !== 'fulfilled') continue
      const found = result.value.items.filter((item) => wanted.has(item.item_id) && item.bbox_px)
      if (found.length && !boxes.length) {
        page = result.value.page
        boxes = found.map((item, index) => ({ item_id: item.item_id, page: result.value.page, bbox_px: item.bbox_px!, label: item.tag ?? String(index + 1) }))
      }
    }
  }
  const citation: Citation = { n: 1, doc_id: docId, page, kind: boxes.length ? 'element' : 'region', bbox_px: boxes[0]?.bbox_px ?? null, item_ids: itemIds, quote: null }
  const answer: Answer = {
    answer_id: `project-view-${docId}`, question: '', doc_ids: [docId],
    answer: { text_md: '', value: null, unit: null, confidence: 1, abstained: false },
    citations: [citation], evidence: { boxes, scene: { doc_id: docId, highlight_item_ids: itemIds, camera_target_item_id: null } },
    trace: [], route: 'index', cost: { usd_total: 0, calls: [] }, latency_ms: 0,
  }
  // A model without a flat drawing position opens in 3D, where the same items glow.
  return { answer, citation, mode: !boxes.length && doc.kind === 'ifc' ? '3d' : '2d' }
}

/** Opens a file, or specific items of a file, in the app's viewer as a side panel (full screen on a phone). */
export function useProjectViewer(): { open: (docId: string, itemIds?: string[]) => void; busy: string | null; error: string; node: ReactNode } {
  const [target, setTarget] = useState<ViewerTarget | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState('')
  const sheet = useViewerSheet()
  const counter = useRef(0)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => controller.current?.abort(), [])
  const open = useCallback((docId: string, itemIds: string[] = []) => {
    controller.current?.abort()
    const next = controller.current = new AbortController()
    setBusy(docId); setError('')
    buildViewerTarget(docId, itemIds, next.signal).then((built) => { if (!next.signal.aborted) setTarget({ ...built, request: ++counter.current }) })
      .catch((err: unknown) => { if (!next.signal.aborted) setError(err instanceof Error ? err.message : 'This file could not be opened.') })
      .finally(() => { if (!next.signal.aborted) setBusy(null) })
  }, [])
  useEffect(() => {
    if (!target) return
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') setTarget(null) }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [target])
  const node = target ? createPortal(<div className="pj-viewer" role="dialog" aria-label="Viewer">
    <button type="button" className="pj-viewer-scrim" aria-label="Close viewer" tabIndex={-1} onClick={() => setTarget(null)} />
    <DocumentViewer key={target.citation.doc_id} answer={target.answer} citation={target.citation} sheet={sheet} initialMode={target.mode} openRequest={target.request} onClose={() => setTarget(null)} />
  </div>, document.body) : null
  return { open, busy, error, node }
}

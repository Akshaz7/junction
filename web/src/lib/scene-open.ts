import type { Answer, Citation } from './types'

/** CONTRACT 3.3: app-feature answers ("show it in 3D", "show on table") carry evidence.scene.open. */
export function sceneOpen(answer: Answer): '3d' | 'ar' | null {
  const open = answer.evidence.scene.open
  return open === '3d' || open === 'ar' ? open : null
}

/** The citation Visualise it opens for an answer: its first citation on the answer's document, else a bare page-1 one. */
export function sceneOpenCitation(answer: Answer): Citation | null {
  const docId = answer.evidence.scene.doc_id || answer.doc_ids[0]
  if (!docId) return null
  return answer.citations.find((entry) => entry.doc_id === docId)
    ?? { n: 1, doc_id: docId, page: 1, kind: 'element', bbox_px: null, item_ids: [...answer.evidence.scene.highlight_item_ids], quote: null }
}

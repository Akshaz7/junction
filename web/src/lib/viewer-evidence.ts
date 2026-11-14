import type { Answer, Bbox, Citation } from './types'

export type ViewerRegion = { id: string; label: string; bbox: Bbox; text: boolean }

export function viewerEvidence(answer: Answer, citation: Citation): { regions: ViewerRegion[]; initial: number } {
  const pageCitations = answer.citations.filter((item) => item.doc_id === citation.doc_id && item.page === citation.page)
  const itemIds = new Set(pageCitations.flatMap((item) => item.item_ids))
  // Boxes have no doc_id in v2: use the scene doc (or sole answer doc), then citation item IDs.
  const boxDoc = answer.evidence.scene.doc_id || (answer.doc_ids.length === 1 ? answer.doc_ids[0] : null)
  const regions: ViewerRegion[] = answer.evidence.boxes
    .filter((box) => box.page === citation.page && (boxDoc === citation.doc_id || itemIds.has(box.item_id)))
    .map((box) => ({ id: box.item_id, label: box.label, bbox: box.bbox_px, text: false }))
  for (const source of pageCitations) {
    if (source.bbox_px && (source.kind === 'text' || !source.item_ids.some((id) => regions.some((region) => region.id === id)))) {
      regions.push({ id: `citation-${source.n}`, label: String(source.n), bbox: source.bbox_px, text: source.kind === 'text' })
    }
  }
  const initial = citation.kind === 'text'
    ? regions.findIndex((region) => region.id === `citation-${citation.n}`)
    : regions.findIndex((region) => citation.item_ids.includes(region.id) || region.id === `citation-${citation.n}`)
  return { regions, initial: Math.max(0, initial) }
}

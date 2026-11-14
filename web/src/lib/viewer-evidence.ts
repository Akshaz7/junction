import type { Answer, Bbox, Citation } from './types'
import { kindFromItemId } from './kind-colors'

export type ViewerRegion = { id: string; label: string; bbox: Bbox; text: boolean; /** Item kind for the fixed kind colour (plan-map ids carry it). */ kind?: string | null }
export type ViewerSource = { id: string; label: string; bbox: Bbox | null; itemIds: string[] }

export function viewerEvidence(answer: Answer, citation: Citation): { regions: ViewerRegion[]; sources: ViewerSource[]; initial: number } {
  const pageCitations = answer.citations.filter((item) => item.doc_id === citation.doc_id && item.page === citation.page)
  const itemIds = new Set(pageCitations.flatMap((item) => item.item_ids))
  // Boxes have no doc_id in v2: use the scene doc (or sole answer doc), then citation item IDs.
  const boxDoc = answer.evidence.scene.doc_id || (answer.doc_ids.length === 1 ? answer.doc_ids[0] : null)
  const regions: ViewerRegion[] = answer.evidence.boxes
    .filter((box) => box.page === citation.page && (boxDoc === citation.doc_id || itemIds.has(box.item_id)))
    .map((box) => ({ id: box.item_id, label: box.label, bbox: box.bbox_px, text: false, kind: kindFromItemId(box.item_id) }))
  for (const source of pageCitations) {
    if (source.bbox_px && (source.kind === 'text' || !source.item_ids.some((id) => regions.some((region) => region.id === id)))) {
      regions.push({ id: `citation-${source.n}`, label: String(source.n), bbox: source.bbox_px, text: source.kind === 'text' })
    }
  }
  const sources: ViewerSource[] = regions.map((region) => ({
    id: region.id, label: region.label, bbox: region.bbox,
    itemIds: pageCitations.find((source) => region.id === `citation-${source.n}`)?.item_ids ?? [region.id],
  }))
  // IFC citations can identify real elements without any page coordinates.
  for (const source of pageCitations) {
    for (const id of source.item_ids) {
      if (!sources.some((entry) => entry.itemIds.includes(id))) {
        sources.push({ id, label: String(source.n), bbox: null, itemIds: [id] })
      }
    }
  }
  if (!sources.length && pageCitations.length && boxDoc === citation.doc_id) {
    for (const id of new Set(answer.evidence.scene.highlight_item_ids)) {
      sources.push({ id, label: String(sources.length + 1), bbox: null, itemIds: [id] })
    }
  }
  const initial = citation.kind === 'text'
    ? sources.findIndex((source) => source.id === `citation-${citation.n}`)
    : sources.findIndex((source) => source.itemIds.some((id) => citation.item_ids.includes(id)) || source.id === `citation-${citation.n}`)
  return { regions, sources, initial: Math.max(0, initial) }
}

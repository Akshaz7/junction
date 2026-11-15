import type { Bbox } from './types'
import type { ViewerRegion, ViewerSource } from './viewer-evidence'
import type { WallDetails } from './wall-details'

export interface ItemPlace {
  doc_id: string
  page: number
  bbox_px: Bbox | null
  storey: string | null
}

export interface LinkedItem {
  item_id: string
  kind: string | null
  tag: string | null
  name: string | null
  storey: string | null
  type_name: string | null
  props: Record<string, unknown>
  wall_details?: WallDetails | null
  places: ItemPlace[]
}

export class LinkedApi {
  constructor(private transport: typeof fetch = (...args) => fetch(...args)) {}
  async get(docId: string, reference: string, signal?: AbortSignal, byTag = false): Promise<LinkedItem> {
    const response = await this.transport(`/api/docs/${encodeURIComponent(docId)}/${byTag ? 'tags' : 'items'}/${encodeURIComponent(reference)}`, { signal })
    if (!response.ok) throw new Error(response.status === 404
      ? 'No item details are available for this drawing reference.'
      : `Item details could not be loaded (${response.status}). Please try again.`)
    return response.json() as Promise<LinkedItem>
  }
}
export const linkedApi = new LinkedApi()

export function propertyValue(value: unknown): string {
  if (value === null || value === undefined) return 'Not supplied'
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/** A related place uses its own page coordinates, never the previous page's boxes. */
export function placeEvidence(place: ItemPlace, item: LinkedItem): { regions: ViewerRegion[]; sources: ViewerSource[]; initial: number } {
  const bbox = place.bbox_px?.length === 4 && place.bbox_px.every(Number.isFinite) ? place.bbox_px : null
  const label = item.tag || '1'
  return {
    regions: bbox ? [{ id: item.item_id, label, bbox, text: false, kind: item.kind }] : [],
    sources: [{ id: item.item_id, label, bbox, itemIds: [item.item_id] }],
    initial: 0,
  }
}

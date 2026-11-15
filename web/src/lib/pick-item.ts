import type { Bbox } from './types'

export interface PickBox { id: string; bbox: Bbox }

/**
 * Inside an aggregate highlight (one box covering several items), pick the item under the click:
 * the smallest candidate whose box, grown by `tolerance` page pixels, contains the point.
 * Returns null when nothing is hit so the caller falls back to the aggregate.
 */
export function pickItemAt(point: [number, number], candidates: PickBox[], allowed: string[], tolerance = 0): string | null {
  const allow = new Set(allowed)
  let best: { id: string; area: number; gap: number } | null = null
  for (const { id, bbox } of candidates) {
    if (!allow.has(id) || bbox.length !== 4 || !bbox.every(Number.isFinite)) continue
    const [x0, y0, x1, y1] = bbox
    if (point[0] < x0 - tolerance || point[0] > x1 + tolerance || point[1] < y0 - tolerance || point[1] > y1 + tolerance) continue
    const gap = Math.max(x0 - point[0], point[0] - x1, y0 - point[1], point[1] - y1, 0)
    const area = (x1 - x0) * (y1 - y0)
    if (!best || gap < best.gap || (gap === best.gap && area < best.area)) best = { id, area, gap }
  }
  return best?.id ?? null
}
